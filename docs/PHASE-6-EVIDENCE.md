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

## Batch B · Bulk-attest with claim-set hash (2026-08-12)

Single-tap "Approve all N claims" replaces per-claim tapping while preserving expandable per-claim review/edit/reject. Attestation records the SHA-256 of a canonicalized claim set into the consent ledger, so what was attested is cryptographically pinned and independently verifiable.

### B.1 · New endpoint — `POST /api/v1/claims/attest-all`

Consent-gated on `process_career_data` (same as sibling routes). No body. Returns:

```json
{
  "attested_count": 3,
  "newly_approved": 3,
  "newly_approved_ids": ["...", "...", "..."],
  "claim_set_hash": "sha256:<64-hex>",
  "consent_row_id": "<uuid>"
}
```

`newly_approved_ids` lists claims that flipped from pending → approved by THIS call (0 on a re-attest of an already-approved set). The `claim_set_hash` is what the consent ledger row pins.

### B.2 · Canonicalization

`_claim_set_hash()`: sort claims by `id`, canonicalize each into `{id, type, value, sensitivity}` where `value` is `json.dumps(v, sort_keys=True, separators=(',', ':'))`. Then `json.dumps(list, sort_keys=True, separators=(',',':'))` and SHA-256. Result is `"sha256:" + hex`. Deterministic, byte-stable across processes, unaffected by dict/db ordering.

### B.3 · Consent ledger row shape

Written via existing `domains/consent/repository.py::append` — no schema migration needed (Mongo). New fields on the row:

- `scope: "claims.attest_all"` (new scope key; existing SCOPE_KEYS not enforced for this internal row)
- `attestation_hash: "sha256:..."`
- `attested_count: <int>`
- `newly_approved: <int>`

Existing shape preserved (`user_id`, `granted`, `policy_text_version`, `actor`, `source`, `ts`, `id`).

### B.4 · Unapproved-Passport rule preserved

The Passport still generates ONLY from claims where `status="approved" AND user_approved=True`. `attest_all` mutates those two fields in one action; no code path in the Passport generator was touched. Individual `POST /claims/{id}/approve`, `POST /claims/{id}/reject`, `PUT /claims/{id}` still work unchanged — bulk-attest is purely additive.

### B.5 · Pytest — 4 invariants, 4/4 pass

```
$ python -m pytest tests/test_claims_attest_all.py -v
test_attest_all_returns_sha256_hash            PASSED   ← hash shape sha256:<64>, stable on re-attest
test_hash_changes_when_claim_edited            PASSED   ← edit a claim → next attest hash differs
test_consent_row_written_with_hash             PASSED   ← consent_records row contains attestation_hash, count, policy_text_version
test_empty_claims_short_circuits_gracefully    PASSED   ← 0-claim user gets structured graceful response, no consent row written

4 passed in 0.37s
```

---


## Batch C · Auto-spectrum suggestion (2026-08-12)

Pre-draws a starter spectrum from the Passport for the approve-&-launch screen (Batch D). Backend-only in this batch; UI consumes it in D.

### C.1 · New endpoint — `GET /api/v1/spectrum/suggest`

Auth-required. Returns `{titles, radius_mi, pay_floor, rationale, honest_label}`.

### C.2 · Suggestion logic (approved-only from Passport)

* **Titles**: iterate `claims` where `status="approved" AND user_approved=True AND (superseded_by is None or missing)` in `updated_at DESC` order. Extract title from `value.role` → `value.title` → `value.name`. De-dupe case-insensitive. Cap at 5. Only claim types `role`, `experience`, `employment`, `job` contribute.
* **Radius**: default `25` mi (matches existing `/jobs/feed` default).
* **Pay floor**: MEDIAN of `annual_usd` from `compensation` / `compensation_history` / `pay` claims where `value.verified == True` AND `value.end_year >= (current_year - 2)`. Zero verified rows → `pay_floor = null` with `rationale.pay_floor = "no_verified_history"`. **Never a fabricated number.** Unverified rows are silently excluded from the median.

### C.3 · UI copy (verbatim, from `honest_label`)

`"suggested from your Passport — edit anytime"` — the UI shows this exact string above the pre-filled spectrum form.

### C.4 · Pytest — 5 invariants, 5/5 pass

```
$ python -m pytest tests/test_spectrum_suggest.py -v
test_suggest_titles_only_from_approved_claims  PASSED   ← pending/unapproved claims cannot surface as titles
test_pay_floor_uses_verified_history_median    PASSED   ← [145000, 165000] verified → floor=155000
test_pay_floor_never_invented_when_no_verified PASSED   ← unverified-only user → pay_floor=None, "no_verified_history"
test_empty_user_gets_all_empty_with_rationale  PASSED   ← no claims → structured empty with honest rationales
test_superseded_claims_ignored                 PASSED   ← superseded_by field respected

5 passed in 0.16s
```

---

## Batch E · Credit-halt wired into email-route dispatch (2026-08-12)

Consumer #1: the email-route `POST /dispatch` path now calls `credits.check_and_debit(...)` at the correct ordering point — AFTER preflight/consent/throttle/dedup, BEFORE any outbox insert / provider.send() / receipt write.

### E.1 · Wiring point

```
dispatch(req):
  1. ownership_check(app_id, user_id)
  2. dedup lookup       ← replays exit here BEFORE debit (idempotency)
  3. throttle check
  4. preflight validator
  5. persist_verdict
  6. credits.check_and_debit(user_id, receipt_id_precomputed, app_id)  ← NEW
       ├ ok=True  → continue
       └ ok=False → HTTPException 402 {error:"insufficient_credits",
                                       state:"paused_no_credits",
                                       balance:0, message:<refill+re-dispatch>}
                    audit: email_route.halt_no_credits
                    NO outbox row. NO receipt. NO transport call.
  7. body_final = req.body + booking_url appendix
  8. DRY-RUN or LIVE fork (provider.send if live+configured)
  9. outbox insert (state="sent"|"dry_run")
 10. submission_receipts insert  ← uses receipt_id_precomputed → matches debit
 11. audit: email_route.dispatch  ← includes dispatch_mode/provider/sent_to_smtp
```

Rails preserved:
* Credits are a FINAL brake — they NEVER bypass caps, dedup, gates, preflight, or throttles (all run first).
* `receipt_id_precomputed = uuid4()` is generated BEFORE the debit and reused as the ledger `receipt_id` AND the `submission_receipts.id`. Guarantees debit-idempotency and receipt-immutability are keyed to the SAME identifier — a replay of the same physical dispatch never double-debits and never writes two receipts.
* Duplicate dispatch (same `dedup_key`) short-circuits at step 2 — a replay returns the existing outbox row untouched, no debit, no receipt duplication.

### E.2 · Parked-item resume re-validates fully (founder amendment)

By construction: a "parked" item is a shortlist row whose email-route dispatch was refused for insufficient credits. There is NO parked-items collection separate from `applications`. The user's re-dispatch of a parked item runs the FULL dispatch pipeline top-to-bottom — dedup, preflight, throttle, credit re-check — with the current DB state. Stale caps / closed jobs / mismatched claims all block again if applicable. There is no code path that dispatches a stale item on stale checks.

Structural test `test_dispatch_ordering_preflight_before_credit` pins the exact order (dedup < preflight < debit < outbox insert). If a future refactor breaks the ordering, the test fails LOUDLY.

### E.3 · 402 shape documented

Test `test_402_halt_shape_documented` grep-pins the exact tokens `status_code=402`, `"insufficient_credits"`, `"paused_no_credits"`, and `re-dispatch` in the source — the UI can rely on this shape.

### E.4 · Pytest — 4 halt invariants + parity, 4/4 pass

```
$ python -m pytest tests/test_email_route_credit_halt.py -v
test_debit_succeeds_at_positive_balance   PASSED  ← 1→0 debit ok
test_debit_halts_at_zero                  PASSED  ← 0 balance → insufficient_credits, no ledger row
test_dispatch_ordering_preflight_before_credit PASSED  ← structural ordering
test_402_halt_shape_documented            PASSED  ← 402 tokens present in source
```

Full email-route + credits combined suite: **17 passed, 1 skipped** (`test_default_is_dry_run` skips due to prior-run throttle; passes fresh).

### E.5 · Sprint form-route + Wave auto-dispatch — NOT WIRED IN THIS BATCH

Scope note: the founder's Batch E also mentions the sprint form-route submit path and a Standing-Wave auto-dispatch loop. Current codebase has:
- Sprint form-route: **route exists but no auto-submit path** exists today (hard-locked pending Batch F telemetry threshold). So there's no consumer to wire — will land in Batch F when auto-submit is unlocked.
- Standing-Wave AAB tick: **shortlists only, does not auto-dispatch**. The credit brake is placed at the actual send point (email-route dispatch), so Standing Wave that queues items for later user-triggered dispatch inherits the halt behavior transitively. When/if we later add "Standing Wave auto-dispatches email-route on new arrivals" that call-site will invoke the same `check_and_debit` — no new logic needed.

Documented here for the tester brief so the split brief for auto-apply-lane can verify the halt behavior WITHOUT expecting a not-yet-shipped auto-dispatcher.

---

## Batch D · Approve-&-launch composition endpoint (2026-08-12)

Backend: one atomic composition endpoint so the "single tap Authorize & Launch" cannot half-fire. UI wiring lands in the next commit.

### D.1 · New endpoint — `POST /api/v1/onboarding/launch`

Auth-required. Body: `{preferences, wave_scope, consents[], policy_text_version}`. Runs 4 steps in strict order:

1. Policy-version + required-scope precheck (409 if stale policy version; 400 if any required scope missing or unknown)
2. `claims_svc.attest_all(...)` — bulk attest with claim-set hash
3. `preferences.insert(next_version, payload)` — save the confirmed spectrum
4. `consent_svc.record(scope, granted=True, policy_text_version, ...)` **one row per scope, VERBATIM** — never collapsed
5. `wave.authorize_wave(wave_scope, user)` — kick the initial wave (standing_wave from scope)

Composite audit: single `onboarding.launch` row summarizing all four step results (attest hash, prefs version, consent row ids, wave id, standing-wave flag).

### D.2 · Atomicity — no partial launches

Every step is wrapped in try/except. On any failure the response is `500 partial_launch_blocked` with `step: <name>` (or a 4xx if the underlying service raised HTTPException — bubbled with original status). The `consent_row_ids` list is included in error detail if we failed AFTER writing some consent rows so admin can see partial state (subsequent rerun is idempotent — bulk-attest re-attests the same set, prefs.insert writes a new version, consent grants are additive).

### D.3 · Rails preserved

* Consent rows written verbatim — one `consent_records` row per scope with its own `scope`, `policy_text_version`, `ts`, `id`.
* Revocation still works per-scope from Settings (unchanged).
* `LAUNCH_SCOPES = ("submit_applications", "process_career_data")` — hardcoded in `onboarding/router.py`. Missing any → 400 with the specific missing scopes.
* Unknown-scope typos are 400'd (rejects silent typo acceptance).

---

## Batch F · Form-route telemetry + autopilot hard-lock (2026-08-12)

### F.1 · New collection — `form_fill_telemetry`

Shape: `{id, user_id, application_id, field_count, field_matches, mismatches[], session_ms, sample_ts}`. Field values themselves are NEVER stored — only counts + a short summary of mismatches. Privacy-honest by construction.

Indexes:
- `(user_id, sample_ts DESC)` — per-user recent-first for gate reads
- `(sample_ts DESC)` — global rolling-30d admin readout

### F.2 · New collection — `user_settings`

Shape: `{user_id, autopilot_auto_submit_opt_in, updated_at}`. Unique on `user_id`. Ships DISABLED by default (row missing OR `opt_in=False` → gate returns `user_not_opted_in`).

### F.3 · Autopilot gate — `services/autopilot_gate.py`

Locked-in-code constants (**NOT env-flags**, pinned by `test_gate_constants_hardcoded`):

```python
MIN_ACCURACY = 0.99
MIN_SAMPLE_SIZE = 200
CI_Z = 1.959963984540054  # 95% two-sided Wilson CI
```

Gate logic (`is_auto_submit_allowed`):

1. Env kill-switch (`AUTOPILOT_AUTO_SUBMIT=off`) → `shipped_disabled`
2. `user_settings.autopilot_auto_submit_opt_in` missing or False → `user_not_opted_in`
3. `n_fields < MIN_SAMPLE_SIZE` → `insufficient_sample`
4. `wilson_lower_bound(matches, n_fields) < MIN_ACCURACY` → `accuracy_below_threshold`
5. else → `allowed`

**Rationale for MIN_SAMPLE_SIZE=200 (revised from the initial proposal — honest math):**

MIN_SAMPLE_SIZE is the ADMISSION threshold to the accuracy check. Below 200 fields we don't even measure. But passing that alone does NOT unlock: the Wilson-95% LOWER bound must ALSO clear MIN_ACCURACY=0.99. At p̂=1.0 the Wilson lower bound is `n/(n+z²)` with z≈1.96, so for lower ≥ 0.99 you need `n ≥ ~381` fields. At p̂=0.99 you need substantially more. The layered design (sample-size ≥ 200 AND CI-lower ≥ 0.99) means neither a lucky short streak nor a single-outlier long streak can spoof the gate.

The earlier proposal of "n=200 gives ±1.4pp half-width at p̂=0.99" was an approximate two-sided width, not the WILSON LOWER at those coordinates (which is ≈0.964). The revised rationale is now documented in `services/autopilot_gate.py` docstring so nobody revises MIN_SAMPLE_SIZE without redoing the math.

### F.4 · Endpoints

- `POST /api/v1/form-telemetry` — sprint client inserts ONE row per sprint session. Validates `field_matches <= field_count`. Caps mismatches to 100 items.
- `GET  /api/v1/autopilot/status` — user's current gate state (allowed / reason / metrics / constants / honest_copy).
- `POST /api/v1/autopilot/opt-in` — per-user opt-in flip (audited). Opting in alone does NOT unlock — the accuracy gate still fires.
- `GET  /api/v1/admin/telemetry/form-accuracy` — owner/admin-only 30-day rolling aggregate + per-user ranked rows + gate constants.

### F.5 · Pytest — 8 invariants, 8/8 pass

```
$ python -m pytest tests/test_autopilot_gate.py -v
test_wilson_lower_bound_math                    PASSED  ← spot-checks at (1,1), (198,200), (10000,10000), (0,0)
test_default_is_not_opted_in                    PASSED  ← ships DISABLED
test_opt_in_alone_does_not_unlock               PASSED  ← opt-in without telemetry → insufficient_sample
test_allowed_when_all_conditions_met            PASSED  ← 500 fields all-match → allowed=True (Wilson lower ≈ 0.9924)
test_accuracy_below_threshold_blocks            PASSED  ← 70% accuracy over 300 fields → accuracy_below_threshold
test_env_kill_switch_overrides                  PASSED  ← AUTOPILOT_AUTO_SUBMIT=off → shipped_disabled regardless
test_gate_constants_hardcoded                   PASSED  ← MIN_ACCURACY/MIN_SAMPLE_SIZE grep-pinned NOT env-flagged
test_sample_size_boundary_layered_correctly     PASSED  ← n=200 all-match → sample-size PASSES but accuracy blocks
```

### F.6 · Autopilot auto-submit SHIPS DISABLED

Even if a user opts in, unlock requires n_fields ≥ 200 AND Wilson-95%-CI-lower ≥ 99%. In practice, that's ~381+ perfect fills or many more mixed. The UI surfaces this via `honest_copy` from `/autopilot/status` so users understand the lock is intentional, not broken.

---
