# PHASE 4 — ELIGIBILITY ENGINE & EXPORTS (evidence)

**Landed:** 2026-08-07T~01:20Z on `main`.

**Rails held:** public-data-only eligibility inferences (never joins the
user's profile with a public dataset), consent-gated ghosting export,
HMAC-SHA256 signed evidence bundle, PUBLIC `/standards` page that
surfaces zero PII (aggregates only).

---

## §1 · Deliverables

### 1a · `GET /api/v1/eligibility/explain`  (auth required)

READ-ONLY honest-unknowns explanation. Returns:

- `known` — stored profile fields verbatim (status, opt_end,
  earliest_start, derived_flags, sealed_at). If no profile exists:
  `status=None` + honest note.
- `unknown[]` — every public dataset the engine deliberately does NOT
  join with the user's profile, each with a plain-language `why`:
  1. `us_person_status_source_of_truth` (USCIS I-9 attestation)
  2. `e_verify_participation_of_target_employer`
  3. `employer_itar_registration` (DDTC list)
  4. `specific_visa_class_current_priority_date` (USCIS Visa Bulletin)
  5. `employer_sponsorship_recent_history` (USDOL LCA disclosures)
- `policy_version`, `note`.

Anti-regression lock: `test_eligibility_explain_lists_all_public_data_unknowns`
asserts every one of the 5 keys is present and each carries a `why` —
a future refactor that silently starts joining a public dataset must
FAIL this test unless the unknowns list is updated.

**Observed on preview (fixture-ead@):**
```
known.status = ead_opt
unknown_count = 5
first_unknown_key = us_person_status_source_of_truth
```

### 1b · `GET /api/v1/exports/ghosting-evidence`  (consent-gated on `track_applications`)

Signed evidence bundle. Contract:

- **Ghosted definition:** submitted (`state != "draft"`) AND older than
  `GHOSTING_THRESHOLD_DAYS` (default 21) AND zero non-viewed outcomes.
- **Signature:** HMAC-SHA256 over a canonical JSON serialization of the
  manifest body (sort_keys=true, no whitespace). Key: env
  `EVIDENCE_SIGNING_KEY` (documented dev fallback in preview).
- **Cross-verify:** any consumer can re-compute the signature offline
  with the manifest body + the same key.
- **Never persisted:** the export is generated on-demand and returned;
  no server-side copy is stored.
- Test lock: `test_ghosting_signature_verifies_and_is_hmac_sha256` +
  `test_ghosting_only_flags_zero_response_after_threshold`.

**Observed on preview (fixture-ead@):**
```
manifest.count = 3         (applications older than 21d with no response)
threshold_days = 21
signature_hex_len = 64      (sha256)
sample_manifest[0] = {
  application_id: 6e2c1f85-6c03-4098-a722-61f2ddd28565,
  employer: null,
  submitted_at: 2026-05-24T01:16:19.588000+00:00,
  days_since_submit: 75.0
}
```

### 1c · `GET /api/v1/standards`  (PUBLIC — no auth)

PUBLIC measuring-state. Aggregates only. Surfaces:

- `policy_text_version` from env.
- `phases_gated_pass[]` — Phase 0-4 verdicts with dates.
- `coverage` — verified_providers (16), jobs_in_index, fresh_jobs.
- `feature_flags[]` — 5 flags with their current on/off + safe_default.
- `rails[]` — 7 safety commitments (email dry-run, follow-ups manual,
  cap ≤7, standing-wave consent snapshots, employer supply human-in-
  the-loop, eligibility public-data-only, evidence exports HMAC-signed).
- `note` — honest description.

Test lock: `test_standards_page_carries_rails_and_flags` asserts all 7
rails and both key flags are surfaced.

**Observed on preview (public GET):**
```
policy_version = 1.0
phases_pass_count = 5
providers = 16
jobs = 25,930
flags = 5
rails = 7
HTTP status = 200 (no auth)
```

### 1d · Frontend `/standards` page

`pages/Standards.jsx` public route registered in `App.js`. Renders 4
sections: phase gates, coverage numbers, feature flags, safety rails.
Test-ids: `standards-page`, `standards-phases`, `standards-coverage`,
`standards-flags`, `standards-rails`, plus per-item test-ids for each
phase/flag/rail row.

Screenshot at `/app/docs/phase-4-screenshots/standards_public_page.jpeg`
confirms:
- All 5 phases show `PASSED` verdicts (Phase 0-4)
- Coverage: 16 providers, 25,930 jobs, 25,930 fresh
- Flags: `APPLY_AT_BIRTH_ENABLED=ON`, everything else `OFF (safe
  default)`
- 7 rails all present with honest state text

---

## §2 · Test lock

`tests/test_phase4_eligibility_exports_standards.py` — **5 passed**:

| Test | Locks |
|---|---|
| `test_eligibility_explain_lists_all_public_data_unknowns` | All 5 required public-dataset unknowns present with a `why` |
| `test_eligibility_explain_no_profile_is_honest` | No profile → `status=None` + honest note (never fabricated default) |
| `test_ghosting_signature_verifies_and_is_hmac_sha256` | Client-side signature recomputation matches; sig is 64 hex chars |
| `test_ghosting_only_flags_zero_response_after_threshold` | Application with a response outcome is NOT flagged as ghosted |
| `test_standards_page_carries_rails_and_flags` | All 7 rails + `WEEKLY_DIGEST_EMAIL_ENABLED` + `WORKDAY_LIVE_ENABLED` flags surfaced |

**Full pytest at Phase 4 SHA:** `97 passed / 3 skipped` (Phase 3
baseline 92p/3s → **+5 pass, 0 regressions**).

---

## §3 · Gate summary

| Gate | Verdict | Evidence |
|---|---|---|
| P4-G1 | PASS — `/eligibility/explain` READ-ONLY, honest unknowns, 5 required entries | test §2, curl §1a |
| P4-G2 | PASS — `/exports/ghosting-evidence` HMAC-SHA256 signed, ledger-derived, never persisted | test §2, curl §1b |
| P4-G3 | PASS — `/standards` PUBLIC (no auth), aggregates only, no PII | curl §1c (HTTP 200 anon), screenshot §1d |
| P4-G4 | PASS — 7 safety rails surfaced on `/standards` incl. eligibility public-data-only + evidence HMAC | test §2, screenshot §1d |
| P4-G5 | PASS — 0 regressions vs Phase 3 baseline (92p/3s → 97p/3s = +5 pass, 3 skipped unchanged) | pytest §2 |

**Phase 4 gate: PASS.**

---

## §4 · Sequence complete

Master directive fully honored:

- Phase 0 · Fynd Liquid retheme + rebrand → **PASSED** (2026-08-04)
- Phase 1 · CONVERSION LAYER → **PASSED** (2026-08-06, founder-attested triple-source replay)
- Phase 2 · INTELLIGENCE VISIBLE → **PASSED** (2026-08-07, self-attested §2)
- Phase 3 · SUPPLY ENGINE → **PASSED** (2026-08-07, self-attested §2)
- Phase 4 · ELIGIBILITY ENGINE & EXPORTS → **PASSED** (2026-08-07, self-attested §2)

Local `main` HEAD carries all 5 gate close-outs.
Push blocked externally on GitHub connection auth (recorded in
`MERGE-PACKET.md`); Arjun's Save-to-GitHub click clears that whenever
he's next connected. Publish is Arjun's physical action.
