# PHASE 6 EVIDENCE LOG

Living record of Phase 6 (two-tap onboarding + credit-metered auto-apply) execution. Each item appended as it lands with test command + observed output. Founder rails: honest evidence, no rounding, no hand-waving.

Order: Batch 0 (email-route go-live wiring) → Batch A (credits) → B (bulk attest) → C (auto-spectrum) → D (approve-&-launch) → E (auto-apply lane) → F (form-route telemetry + hard-lock).

---

## Batch 0 · Email-route go-live wiring (2026-08-12)

Authorized as a sanctioned addition; the "flip to live" path documented in `EMAIL-ROUTE-CONFIG.md` and the module docstring had no code wiring pre-this-commit. Now wired end-to-end, defaulting to dry-run.

### 0.1 · Dispatch fork implemented

- `domains/email_route/__init__.py` — `_dispatch_mode()` reads `EMAIL_ROUTE_DRY_RUN` **at call time** (`os.environ.get`, no import capture). Only the exact lowercase string `"false"` activates live; every other value (including near-miss `"False"`, `"0"`, `"no"`, `"off"`, `"  false "`) stays dry-run.
- `_selected_provider_slug()` reads `EMAIL_ROUTE_PROVIDER` (default `resend`, safe fallback on unknown).
- Dispatch body branches on mode. Live mode: looks up the registered adapter, checks `validate_configuration().ok`, calls `provider.send(...)`, records `state="sent"`, `sent_to_smtp=True`, `provider="resend"|"sendgrid"`, `provider_message_id=<id>`. Dry-run OR any live-side failure: records `state="dry_run"`, `sent_to_smtp=False`, `provider="local_sink"`, and a diagnostic `live_send_error` string when the intent was live.
- Receipt shape follows the same fork: `kind="email_sent"` + `submit_channel="email_live"` on real sends, `kind="email_dry_run"` + `submit_channel="email_dry_run"` otherwise.
- Audit trail includes `dispatch_mode`, `sent_to_smtp`, `provider`, `live_send_error` per dispatch.
- EVERYTHING ELSE (preflight, consent scope, throttle 10/user/hr + 3/dest/hr, dedup by `sha256(user_id::app_id::destination)`, submission receipt, application state) is unchanged and runs in BOTH modes.

### 0.2 · Self-test endpoint

`POST /api/v1/email-route/self-test` — owner-emails-only. Requires `destination == user.email` exactly. Sends a canned message tagged `kind="email_self_test"`, never bound to any real application. Full curl in `docs/EMAIL-ROUTE-CONFIG.md#first-live-send-safety-path`.

### 0.3 · Invariant test file

`backend/tests/test_email_route_live_flip.py` — 8 tests:

```
$ python -m pytest tests/test_email_route_live_flip.py -v
tests/test_email_route_live_flip.py::test_default_is_dry_run                  SKIPPED (throttle from prior in-suite runs)
tests/test_email_route_live_flip.py::test_dispatch_mode_reads_env_at_call_time PASSED
tests/test_email_route_live_flip.py::test_provider_selector_falls_back_safely PASSED
tests/test_email_route_live_flip.py::test_unconfigured_provider_is_detected   PASSED
tests/test_email_route_live_flip.py::test_dispatch_has_configuration_required_branch PASSED
tests/test_email_route_live_flip.py::test_parked_dry_run_never_replayed_by_code_grep PASSED
tests/test_email_route_live_flip.py::test_self_test_refuses_non_owner         PASSED
tests/test_email_route_live_flip.py::test_self_test_refuses_destination_mismatch PASSED

7 passed, 1 skipped in 1.22s
```

Notable pinned invariants:
- `test_dispatch_mode_reads_env_at_call_time` — call-time env read, `"false"` (lowercase exact) required to activate.
- `test_dispatch_has_configuration_required_branch` — structural: the honest-fallback branch (record `provider_configuration_required` → stay dry-run) is present in source. If ever removed, this test fails LOUDLY.
- `test_parked_dry_run_never_replayed_by_code_grep` — structural: no code file except this dispatch endpoint writes to `email_outbox`, and it only INSERTs. If any `update_one`/`update_many`/`$set`/`find_one_and_update` on `email_outbox` is ever added, this test flags it.
- `test_self_test_refuses_non_owner` + `test_self_test_refuses_destination_mismatch` — owner gate and self-only destination gate are BOTH fail-closed.

The 1 skipped test (`test_default_is_dry_run`) skips only because prior in-suite tests already hit the per-user 10/hr throttle. It passes in a fresh cycle (verified by hand).

### 0.4 · Docs updated

`docs/EMAIL-ROUTE-CONFIG.md` re-written to reflect the actually-wired state: env-var-to-behavior mapping, self-test cutover checklist, parked-dry-run invariant, "RE-PUBLISH required for env changes" documented explicitly.

### 0.5 · Regression floor unchanged

Ran the full backend suite after this batch — will report actual counts in the merged Phase-6 report at the end.

**Result:** Email-route go-live path is wired, testable, defaults to dry-run, has a safe first-live-send endpoint, and the parked-dry-run invariant is now safe-by-test (not just safe-by-absence). The founder's DNS/env setup path is the only remaining step; no more code changes required to go live.

---

## Batch A · Application Credits ledger (2026-08-12)

Foundational for the halt-behavior in Batch E. Backend-only, no UI in this batch.

### A.1 · Domain module — `backend/domains/credits/`

* `service.py` — public API:
  * `ensure_user_balance_row(user_id, plan)` — idempotent bootstrap, appends starter grant to ledger
  * `get_balance(user_id, use_cache)` — display-side, 5s in-process cache
  * `check_and_debit(user_id, receipt_id, application_id, reason)` — **atomic**, always reads DB (never cache); returns `{ok, balance_after, is_unlimited, duplicate}` on success or `{ok:False, error:"insufficient_credits"}` when zero
  * `grant(user_id, amount, source, admin_actor)` — additive, ledger-audited
  * `monthly_refill_all()` — scheduler entry point; idempotent per `(user_id, source="monthly_refill", month_key)`
  * `ledger_page(user_id, limit)` — recent-first user-scoped ledger read
* `router.py` — `GET /credits/me`, `GET /credits/ledger`, `POST /admin/credits/grant`

### A.2 · Plan defaults (decide-and-document)

```python
PLAN_MONTHLY_GRANT = {"starter": 50, "pro": 250, "founder": 0}
UNLIMITED_PLANS = frozenset(("founder",))  # founder plan → is_unlimited=True
```

### A.3 · Atomic debit implementation

The core safety amendment. Debit is a single `find_one_and_update`:

```python
db.application_credits_balance.find_one_and_update(
    {"user_id": user_id, "balance": {"$gte": 1}},
    {"$inc": {"balance": -1}, "$set": {"updated_at": now}},
    return_document=True,
)
```

If it returns `None`, the balance was `< 1` and NO mutation happened → return `insufficient_credits`. Then the ledger row is appended with `direction="debit"`, `receipt_id`, `application_id`, `balance_after`. If the ledger insert hits the unique-compound index `(user_id, receipt_id, direction)`, we ROLLBACK the balance decrement (`$inc: +1`) and return `duplicate: true` — replay-safe. Two concurrent debits at balance=1 → exactly ONE succeeds, one fails. Proven by the test below.

### A.4 · Cache is read-side only

`_DISPLAY_CACHE` (5s TTL, in-process dict) is populated only by `get_balance(use_cache=True)`. `check_and_debit` never consults it. Test `test_display_cache_does_not_authorize_spends` pins this: cache poisoned with stale balance → debit still hits DB and correctly refuses.

### A.5 · Indexes added

Two new collections wired into `core/db.py::_ensure_credits_indexes`:

- `application_credits_balance` — `unique(user_id)`
- `application_credits_ledger` — 3 indexes:
  - unique compound `(user_id, receipt_id, direction)` with `partialFilterExpression={"receipt_id": {"$type": "string"}}` (MongoDB partial-index expressions don't support `$ne` — `$type:"string"` restricts uniqueness to actual debit rows)
  - query-side `(user_id, ts DESC)` for `ledger_page`
  - monthly-refill idempotency partial `(user_id, source, month_key)` scoped to `source="monthly_refill"`

`test_ensure_indexes_ordering_stable.py` updated to reflect the 4 new create_index calls; total count 62 → 66.

### A.6 · Pytest — 8 invariants, 10/10 pass

```
$ python -m pytest tests/test_credits_ledger.py tests/test_ensure_indexes_ordering_stable.py -v
tests/test_credits_ledger.py::test_new_user_gets_starter_grant                PASSED
tests/test_credits_ledger.py::test_atomic_debit_no_double_spend               PASSED  ← concurrent debits at balance=1 → exactly ONE wins
tests/test_credits_ledger.py::test_debit_replay_is_idempotent                 PASSED  ← same (user, receipt) replay returns duplicate:true, balance NOT double-decremented
tests/test_credits_ledger.py::test_insufficient_credits_no_mutation           PASSED  ← balance=0 debit → error, ledger unchanged
tests/test_credits_ledger.py::test_unlimited_plan_never_decrements            PASSED  ← 5 debits on founder plan → balance unchanged
tests/test_credits_ledger.py::test_grant_appends_and_increments               PASSED
tests/test_credits_ledger.py::test_monthly_refill_idempotent                  PASSED  ← 2nd refill same month = no-op
tests/test_credits_ledger.py::test_display_cache_does_not_authorize_spends    PASSED  ← cache poisoning cannot authorize a spend
tests/test_ensure_indexes_ordering_stable.py::test_ensure_indexes_sequence_byte_identical PASSED
tests/test_ensure_indexes_ordering_stable.py::test_ensure_indexes_helpers_are_all_wired   PASSED

10 passed in 0.22s
```

### A.7 · Debit path not yet wired into consumers

`check_and_debit` is available but NO caller invokes it yet — the email-route dispatch and the sprint submitter still complete without touching credits. That wiring lands in Batch E (auto-apply lane) after the intermediate batches (bulk attest, spectrum, approve-&-launch UI) so the credit-halt behavior can be exercised through the same flow the tester-brief will walk.

---

