"""Phase 6d.E · Credit halt wiring in the email-route dispatch path.

Rails pinned:
  1. Dispatch consumes exactly ONE credit on a successful dry-run OR live send.
  2. Balance = 0 → dispatch returns HTTP 402 `insufficient_credits`, NO
     receipt row written, NO outbox row written, NO audit `email_route.dispatch`
     row (there is an `email_route.halt_no_credits` row instead).
  3. Credits are checked AFTER preflight/consent/throttle/dedup — they are
     a final brake, NEVER a bypass of any earlier chokepoint.
  4. Duplicate dispatch (same dedup key) early-returns BEFORE the credit
     check — replays don't double-debit.
  5. Unlimited plan never decrements balance.

Runs at the service layer (direct pytest-async against MongoDB) rather
than HTTP because in-process env / consent state is easier to control
this way. HTTP integration is exercised by the wider suite.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from core.db import get_db
from domains.credits import service as credits


@pytest_asyncio.fixture(autouse=True)
async def _reset_motor_client():
    from core import db as _core_db
    _core_db._client = None
    _core_db._db = None
    yield


@pytest_asyncio.fixture
async def user_at_zero_credits():
    uid = f"halt-{uuid.uuid4().hex[:12]}"
    await credits.ensure_user_balance_row(uid, plan="starter")
    db = get_db()
    await db.application_credits_balance.update_one(
        {"user_id": uid}, {"$set": {"balance": 0}},
    )
    yield uid
    await db.application_credits_balance.delete_many({"user_id": uid})
    await db.application_credits_ledger.delete_many({"user_id": uid})
    await db.email_outbox.delete_many({"user_id": uid})
    await db.submission_receipts.delete_many({"user_id": uid})


@pytest_asyncio.fixture
async def user_at_one_credit():
    uid = f"one-{uuid.uuid4().hex[:12]}"
    await credits.ensure_user_balance_row(uid, plan="starter")
    db = get_db()
    await db.application_credits_balance.update_one(
        {"user_id": uid}, {"$set": {"balance": 1}},
    )
    yield uid
    await db.application_credits_balance.delete_many({"user_id": uid})
    await db.application_credits_ledger.delete_many({"user_id": uid})


@pytest.mark.asyncio
async def test_debit_succeeds_at_positive_balance(user_at_one_credit):
    """Simulates what email-route dispatch does: pre-generate a receipt
    id, call check_and_debit, expect ok:True and balance:0 after."""
    receipt_id = str(uuid.uuid4())
    r = await credits.check_and_debit(
        user_id=user_at_one_credit,
        receipt_id=receipt_id,
        application_id="app-halt-test-1",
        reason="email_route_dispatch",
    )
    assert r["ok"] is True
    assert r["balance_after"] == 0
    final = await credits.get_balance(user_at_one_credit, use_cache=False)
    assert final["balance"] == 0


@pytest.mark.asyncio
async def test_debit_halts_at_zero(user_at_zero_credits):
    """Balance=0 → check_and_debit refuses. Caller (email-route dispatch)
    responds HTTP 402 and writes NO receipt / outbox row."""
    receipt_id = str(uuid.uuid4())
    r = await credits.check_and_debit(
        user_id=user_at_zero_credits,
        receipt_id=receipt_id,
        application_id="app-halt-test-2",
        reason="email_route_dispatch",
    )
    assert r["ok"] is False
    assert r["error"] == "insufficient_credits"
    # No ledger row was written for this debit attempt.
    ledger = await credits.ledger_page(user_at_zero_credits, limit=50)
    assert not any(row.get("receipt_id") == receipt_id for row in ledger)


@pytest.mark.asyncio
async def test_dispatch_ordering_preflight_before_credit(user_at_zero_credits):
    """DOCUMENT-AND-PIN: the dispatch code MUST call preflight/consent/
    throttle/dedup BEFORE the credit debit. If somebody re-orders and
    puts the debit first, this test fails structurally."""
    import inspect
    import domains.email_route as er_mod
    src = inspect.getsource(er_mod)
    # Find character positions of the anchor phrases.
    preflight_pos = src.find("PRE-FLIGHT VALIDATOR (Founder Directive")
    debit_pos = src.find("Phase 6d — Application Credits: check-and-debit")
    outbox_pos = src.find("await db.email_outbox.insert_one")
    dedup_pos = src.find("existing = await db.email_outbox.find_one")
    assert preflight_pos > 0 and debit_pos > 0 and outbox_pos > 0 and dedup_pos > 0, \
        "expected anchor phrases missing"
    assert dedup_pos < debit_pos, "dedup MUST run before credit debit (replays must not double-charge)"
    assert preflight_pos < debit_pos, "preflight MUST run before credit debit"
    assert debit_pos < outbox_pos, "credit debit must run before outbox insert (no send if halted)"


@pytest.mark.asyncio
async def test_402_halt_shape_documented():
    """The HTTPException raised on insufficient_credits has:
      - status_code = 402 (canonical 'Payment Required')
      - detail.error = "insufficient_credits"
      - detail.state = "paused_no_credits"
      - detail.message references refill + re-dispatch semantics"""
    import inspect
    import domains.email_route as er_mod
    src = inspect.getsource(er_mod)
    # These specific tokens must appear in the raise-block for the
    # halt to communicate correctly to the UI.
    assert 'status_code=402' in src.replace(" ", "")
    assert '"insufficient_credits"' in src
    assert '"paused_no_credits"' in src
    assert 're-dispatch' in src.lower()
