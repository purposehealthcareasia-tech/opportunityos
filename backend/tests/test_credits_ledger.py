"""Credits ledger — atomic-debit + halt + idempotency + grant invariants.

Rails pinned by this file:

1. NEW USER gets a starter monthly grant materialized on first read.
2. DEBIT is ATOMIC: `find_one_and_update` with `balance: {$gte: 1}` filter.
   Two concurrent debits at balance=1 → exactly ONE succeeds, one fails
   with `insufficient_credits`. No double-debit possible.
3. IDEMPOTENT on `(user_id, receipt_id, direction)`: replay of the same
   debit hits the ledger unique-index, rolls back the balance, returns
   `duplicate: true`. Balance is never decremented twice for the same
   receipt.
4. INSUFFICIENT CREDITS returns `ok: False, error: "insufficient_credits"`
   WITHOUT any mutation.
5. UNLIMITED PLAN short-circuits — appends audit ledger row, balance
   untouched, always returns ok=True.
6. GRANT + monthly refill are additive; refill is idempotent per
   `(user_id, source="monthly_refill", month_key)`.
7. DISPLAY CACHE is bypassed by the debit path — `get_balance(use_cache=True)`
   never authorizes a spend.

These tests use the direct service-layer API against the live MongoDB
(the same DB the backend hits). Each test uses a unique user_id to
avoid cross-test contention.
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import pytest_asyncio

from core.db import get_db
from domains.credits import service as credits


@pytest_asyncio.fixture(autouse=True)
async def _reset_motor_client_per_test():
    """Motor caches its AsyncIOMotorClient at first `get_db()` call,
    bound to that call's event loop. pytest-asyncio creates a fresh
    event loop per async test — so the cached client from a prior test
    holds a closed loop and raises `RuntimeError: Event loop is closed`
    on second use. Reset before every test so `get_db()` re-binds to
    the current loop. Same pattern as
    `tests/test_receipts_immutability.py:94-96` and
    `tests/test_phase1_standing_wave_tick.py:169`.
    """
    from core import db as _core_db
    _core_db._client = None
    _core_db._db = None
    yield


@pytest_asyncio.fixture
async def fresh_user():
    """Return a unique user_id and clean up its balance/ledger rows at
    teardown so no test pollutes another."""
    uid = f"credits-test-{uuid.uuid4().hex[:12]}"
    yield uid
    db = get_db()
    await db.application_credits_balance.delete_many({"user_id": uid})
    await db.application_credits_ledger.delete_many({"user_id": uid})


# ---------------------------------------------------------------------------
# 1 · New user bootstrap
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_new_user_gets_starter_grant(fresh_user):
    snap = await credits.get_balance(fresh_user, use_cache=False)
    assert snap["balance"] == credits.PLAN_MONTHLY_GRANT["starter"]
    assert snap["plan"] == "starter"
    assert snap["is_unlimited"] is False


# ---------------------------------------------------------------------------
# 2 · Atomic debit under contention — two concurrent debits at balance=1
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_atomic_debit_no_double_spend(fresh_user):
    # Seed balance to exactly 1.
    await credits.ensure_user_balance_row(fresh_user, plan="starter")
    db = get_db()
    await db.application_credits_balance.update_one(
        {"user_id": fresh_user}, {"$set": {"balance": 1}},
    )
    r1_id = f"rcpt-{uuid.uuid4().hex[:8]}"
    r2_id = f"rcpt-{uuid.uuid4().hex[:8]}"
    # Two concurrent debits with DIFFERENT receipt ids — only ONE should
    # succeed at balance=1.
    res1, res2 = await asyncio.gather(
        credits.check_and_debit(user_id=fresh_user, receipt_id=r1_id,
                                  application_id="app-1"),
        credits.check_and_debit(user_id=fresh_user, receipt_id=r2_id,
                                  application_id="app-2"),
    )
    successes = [r for r in (res1, res2) if r.get("ok")]
    failures  = [r for r in (res1, res2) if not r.get("ok")]
    assert len(successes) == 1, f"expected exactly 1 success at balance=1, got: {res1} {res2}"
    assert len(failures) == 1
    assert failures[0]["error"] == "insufficient_credits"
    # Balance must land at exactly 0.
    final = await credits.get_balance(fresh_user, use_cache=False)
    assert final["balance"] == 0


# ---------------------------------------------------------------------------
# 3 · Idempotent debit — same (user, receipt) replay never double-debits
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_debit_replay_is_idempotent(fresh_user):
    await credits.ensure_user_balance_row(fresh_user, plan="starter")
    receipt = f"rcpt-{uuid.uuid4().hex[:8]}"
    r1 = await credits.check_and_debit(user_id=fresh_user, receipt_id=receipt,
                                          application_id="app-x")
    r2 = await credits.check_and_debit(user_id=fresh_user, receipt_id=receipt,
                                          application_id="app-x")
    assert r1["ok"] and r2["ok"]
    # r2 must be recognized as a duplicate; balance must NOT have gone
    # down twice.
    assert r2.get("duplicate") is True, r2
    starter = credits.PLAN_MONTHLY_GRANT["starter"]
    final = await credits.get_balance(fresh_user, use_cache=False)
    assert final["balance"] == starter - 1, final


# ---------------------------------------------------------------------------
# 4 · Insufficient credits — no mutation
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_insufficient_credits_no_mutation(fresh_user):
    await credits.ensure_user_balance_row(fresh_user, plan="starter")
    db = get_db()
    await db.application_credits_balance.update_one(
        {"user_id": fresh_user}, {"$set": {"balance": 0}},
    )
    r = await credits.check_and_debit(user_id=fresh_user, receipt_id="never-debit",
                                          application_id="app-nope")
    assert r["ok"] is False
    assert r["error"] == "insufficient_credits"
    # Balance still zero — nothing changed.
    final = await credits.get_balance(fresh_user, use_cache=False)
    assert final["balance"] == 0
    # Ledger has no matching row (only the bootstrap grant, no debit).
    ledger = await credits.ledger_page(fresh_user, limit=10)
    assert not any(row.get("receipt_id") == "never-debit" for row in ledger)


# ---------------------------------------------------------------------------
# 5 · Unlimited plan — always ok, balance untouched
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_unlimited_plan_never_decrements(fresh_user):
    await credits.ensure_user_balance_row(fresh_user, plan="founder")
    db = get_db()
    # Founder plan defaults to balance=0 with is_unlimited=True — verify.
    row = await db.application_credits_balance.find_one({"user_id": fresh_user})
    assert row["is_unlimited"] is True
    for i in range(5):
        r = await credits.check_and_debit(
            user_id=fresh_user, receipt_id=f"rcpt-unlimited-{i}",
            application_id=f"app-{i}",
        )
        assert r["ok"] is True
        assert r["is_unlimited"] is True
    row2 = await db.application_credits_balance.find_one({"user_id": fresh_user})
    assert row2["balance"] == row["balance"], "unlimited path must NOT change balance"


# ---------------------------------------------------------------------------
# 6 · Grant — additive, audited
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_grant_appends_and_increments(fresh_user):
    await credits.ensure_user_balance_row(fresh_user, plan="starter")
    starter = credits.PLAN_MONTHLY_GRANT["starter"]
    r = await credits.grant(user_id=fresh_user, amount=25,
                              source="promo_beta", admin_actor="test-actor")
    assert r["ok"] is True
    final = await credits.get_balance(fresh_user, use_cache=False)
    assert final["balance"] == starter + 25
    # Ledger has the grant row with `source`.
    ledger = await credits.ledger_page(fresh_user, limit=10)
    grant_row = next((row for row in ledger
                       if row.get("direction") == "grant" and row.get("source") == "promo_beta"), None)
    assert grant_row is not None
    assert grant_row["amount"] == 25
    assert grant_row["admin_actor"] == "test-actor"


# ---------------------------------------------------------------------------
# 7 · Monthly refill idempotency
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_monthly_refill_idempotent(fresh_user):
    await credits.ensure_user_balance_row(fresh_user, plan="starter")
    starter = credits.PLAN_MONTHLY_GRANT["starter"]
    # Debit down to 10 so we can observe the refill delta clearly.
    db = get_db()
    await db.application_credits_balance.update_one(
        {"user_id": fresh_user}, {"$set": {"balance": 10}},
    )
    r1 = await credits.monthly_refill_all()
    b1 = (await credits.get_balance(fresh_user, use_cache=False))["balance"]
    # Refill again SAME month — must be a no-op.
    r2 = await credits.monthly_refill_all()
    b2 = (await credits.get_balance(fresh_user, use_cache=False))["balance"]
    assert b2 == b1, f"refill replay must be no-op: b1={b1} b2={b2}"
    assert b1 == 10 + starter, f"expected 10+{starter}={10+starter}, got {b1}"


# ---------------------------------------------------------------------------
# 8 · Display cache DOES NOT authorize spends
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_display_cache_does_not_authorize_spends(fresh_user):
    await credits.ensure_user_balance_row(fresh_user, plan="starter")
    # Populate the display cache by reading with use_cache=True.
    snap = await credits.get_balance(fresh_user, use_cache=True)
    starter = credits.PLAN_MONTHLY_GRANT["starter"]
    assert snap["balance"] == starter
    # Now directly zero the DB balance (bypass service), leaving the
    # cache lying about it.
    db = get_db()
    await db.application_credits_balance.update_one(
        {"user_id": fresh_user}, {"$set": {"balance": 0}},
    )
    # The DEBIT path must NOT be fooled by the cache — it reads
    # authoritatively.
    r = await credits.check_and_debit(user_id=fresh_user, receipt_id="post-cache",
                                          application_id="app-cache")
    assert r["ok"] is False
    assert r["error"] == "insufficient_credits"
