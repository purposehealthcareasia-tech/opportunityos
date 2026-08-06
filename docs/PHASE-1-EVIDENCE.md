# PHASE 1 — CONVERSION LAYER · Merge-Decision Evidence (living document)

**Branch:** `feat/liquid-ui` (Phase 0 stacked lane, retroactively upgraded to full triple-source PASS via §16 of `PHASE-0-EVIDENCE.md`).
**Rails:** preview only · no merge · no push · no deploy · no `.env` edits · no real submissions · no live email · consent-gated everything · cap NEVER bypassed · wave authorizations logged with scope snapshot · follow-ups never auto-sent.

**Cycle policy (founder directive 2026-08-06):**
* **Atomic reload** — one uvicorn `--reload` for the entire opener + Phase-1 bundle in this exact order: (i) backend rebrand · (ii) scorer-unfreeze with byte-identical proof · (iii) Lighthouse re-measure · (iv) 1a speed-sort · (v) 1b Apply Wave · (vi) 1c booking URL · (vii) 1d follow-up drafts.
* **Gate preserved** — each Phase-1 item still lands with its own evidence section here (focused tests + honest failure states); full Phase-1 tester pass runs at phase end.

---

## §0 — Measured baseline (pre-cycle, 2026-08-06 ~11:00 UTC)

```
python3 -m pytest tests/test_preflight_validator.py tests/test_receipt_compound_index_regression.py \
                  tests/test_consent_scope_enum_guard.py tests/test_apply_at_birth.py \
                  tests/test_form_map_cache.py tests/test_outcome_autopilot.py \
                  tests/test_self_healing.py tests/test_outcomes_endpoints.py \
                  tests/test_surprise_me.py -q --tb=line
```
Result: **62 passed, 0 failed** (measured pre-cycle, unchanged from Phase 0 closeout).

**Fixed-fixture score snapshot for byte-identical proof** (`GET /api/v1/jobs/feed` as `fixture-ead@`, normalized by stripping volatile fields — `discovery`, `polled_at`, `last_polled_at`, `first_seen`, `posted_at`, `served_at`, `cache_key`, `fetched_at`; passing/excluded arrays sorted by `id`):
* `passing_count = 9`, `excluded_count = 22440`
* `passing_scores` (id_prefix, score) sorted by id:
  ```
  00cef519 → 91.97      04e6972b → 91.97      11b20e71 → 75.9
  184814d9 → 91.97      7d1e68b5 → 83.94      d646436d → 75.9
  e0fdf883 → 91.97      e5413a1f → 51.83      f3fad7cc → 83.94
  ```
* `md5(normalized_feed_pre.json)` = **`af9fb9e581ff1a4258bd3dddbc34cdc0`**

---

## §1 — Cycle log (append-only as items land)

_Populated below as each item ships._
