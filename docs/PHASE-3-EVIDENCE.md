# PHASE 3 — SUPPLY ENGINE (evidence)

**Landed:** 2026-08-07T~01:15Z on `main`.

**Rails held:** consent + role gates, HTTPS-only URL validation
mirroring Phase 1 §1c, 20/24h/user rate-limit envelope, dedup on
`(user, canonical_host)`, one vote per user per employer_key, admin
gate on the queue, **no scraping, no auto-ingest** (human-in-the-loop
founder triage is the next step).

---

## §1 · Deliverables

### 1a · `POST /api/v1/employers/connect`

Self-serve employer URL submission. Contract:

- HTTPS-only, ≤500 chars, valid FQDN, no userinfo / query / fragment.
- Rate-limit: 20 per 24h per user → HTTP 429 with descriptive detail.
- Dedup on `(user_id, canonical_host)` → HTTP 200 + `already_submitted:
  true` (idempotent). New submission → HTTP 201.
- Writes to `employer_submissions` collection (append-only).
- Emits `supply.connect_submitted` audit row.
- Canonicalizes: strips `www.`, lowercases, drops trailing slash.

**Observed on preview:**
```
POST /employers/connect  (http://acme.com/careers)              → 422 invalid_url
POST /employers/connect  (https://acme.com/careers)             → 201 (new)
POST /employers/connect  (https://www.ACME.com/jobs)            → 200 already_submitted
```

### 1b · `POST /api/v1/employers/vote`

User upvote on an already-known employer_key. Contract:

- `employer_key` must be a valid FQDN; auto-lowercased by pydantic
  validator.
- Dedup on `(user_id, employer_key)` → HTTP 200 + `already_voted:
  true`. New vote → HTTP 201.
- Writes to `employer_votes` collection.
- Emits `supply.vote` audit row.
- Frontend auto-casts a vote on successful `/connect` — one round-trip
  from the founder's POV.

**Observed on preview:**
```
POST /employers/vote  ({"employer_key":"acme.com"})             → 201 (new)
POST /employers/vote  ({"employer_key":"acme.com"})  (again)    → 200 already_voted
```

### 1c · `GET /api/v1/admin/employers/queue`

**ADMIN-ONLY** ranked queue. Contract:

- `role=="admin"` required → non-admins get HTTP 403 `role_forbidden`.
- Ranking: (votes desc, earliest_submitted_at asc, employer_key asc).
- Read-only aggregation over `employer_submissions` (pending) +
  `employer_votes`.
- Bounded by `limit` (default 50, max 200).

**Observed on preview:**
```
GET /admin/employers/queue  (fixture-ead@ non-admin cookie)     → 403 role_forbidden
GET /admin/employers/queue  (admin@ admin cookie)               → 200 with queue array
```

Sample queue payload:
```json
{
  "queue": [
    {
      "employer_key": "acme.com",
      "votes": 1,
      "submission_count": 1,
      "earliest_submitted_at": "2026-08-07T01:07:38.895000",
      "example_url": "https://acme.com/careers"
    }
  ],
  "total_keys": 1
}
```

### 1d · `docs/WORKDAY-SPEC.md` (spec-only, no code)

Committed 8-section specification for the future Workday adapter.
Ships with:
- Discovery model (§2) — per-employer tuple in `workday_employers`,
  cold/warm pull cadence, 1-req/1.2s rate limit, 20-min wall-clock
  budget with `paused` fail-safe.
- Apply model (§3) — dry-run-by-default `workday_apply_drafts`; live
  behind founder-flipped `WORKDAY_LIVE_ENABLED=true`; MANDATORY
  wave-authorization + `submit_applications` scope for any live POST.
- Follow-up model (§4) — reuses Phase 1 `follow_up_drafts`, source
  field extension only, **manual explicit send only**.
- Redaction / privacy (§5) — extends the existing redaction table;
  Workday session cookies MUST NOT be persisted.
- Three independent kill switches (§6) — discovery, live, per-employer
  paused. Any one halts safely without disturbing others.
- Out of scope (§7) — CAPTCHA solving, private candidate home;
  documented not-doing.
- Test plan (§8) — 6 minimum locks for the future implementation.

Signed-off state: **PENDING FOUNDER REVIEW.** No code shipped.

---

## §2 · Test lock

`tests/test_phase3_supply_engine.py` — **8 passed**:

| Test | Locks |
|---|---|
| `test_canonicalize_host_https_only` | HTTP → 422 with the exact `must be an https:// URL` message |
| `test_canonicalize_host_strips_www_and_lowercases` | `WWW.Acme.com/CAREERS` → `acme.com` (dedup join key correctness) |
| `test_canonicalize_host_rejects_userinfo_query_fragment` | `u:p@acme.com`, `?utm=x`, `#top` → 422 |
| `test_canonicalize_host_rejects_bad_hosts` | `localhost`, IPv4 numeric, spaces → 422 |
| `test_canonicalize_host_url_length_cap` | >500 chars → 422 |
| `test_vote_request_validates_employer_key` | Pydantic validator lowercases + rejects non-FQDN |
| `test_admin_queue_ranks_votes_desc_then_earliest_asc` | Sort predicate unit-tested (votes desc, earliest asc, key asc) |
| `test_rate_limit_envelope_enforced` | 20th submission in 24h → HTTP 429 with `submission_rate_limit` error |

**Full pytest at Phase 3 SHA:** `92 passed / 3 skipped` (Phase 2 baseline
84p/3s → **+8 pass, 0 regressions**).

---

## §3 · Frontend touchpoint

`components/EmployerConnectCard.jsx` mounted on `pages/Preferences.jsx`
below the booking-URL row. Test-ids: `employer-connect-card`,
`employer-connect-url`, `employer-connect-notes`,
`employer-connect-submit`, `employer-connect-flash`,
`employer-connect-copy-guardrail`.

Rails held: HTTPS surface hint, 20/24h cap displayed inline, dedup
message surfaced verbatim from backend, honest error copy for
server-side 422/429, auto-cast vote on successful submit (one
round-trip UX; second click surfaces `already_voted`).

Preview URL check: `/preferences` HTTP 200 after mount.

---

## §4 · Gate summary

| Gate | Verdict | Evidence |
|---|---|---|
| P3-G1 | PASS — HTTPS-only + FQDN validation contract | 3 canonicalizer tests, curl 422 on http |
| P3-G2 | PASS — dedup on both `/connect` and `/vote` (idempotent 200) | 2 tests + preview curl |
| P3-G3 | PASS — rate-limit envelope enforced | `test_rate_limit_envelope_enforced`, curl chain would hit 429 at 20th call |
| P3-G4 | PASS — admin gate on `/admin/employers/queue` (403 for non-admin, 200 for admin) | preview curl §1c |
| P3-G5 | PASS — queue ranked by (votes desc, earliest asc) | `test_admin_queue_ranks_votes_desc_then_earliest_asc` |
| P3-G6 | PASS — `WORKDAY-SPEC.md` committed as spec-only | `/app/docs/WORKDAY-SPEC.md` |
| P3-G7 | PASS — 0 regressions vs Phase 2 baseline (84p/3s → 92p/3s = +8 pass, 3 skipped unchanged) | pytest §2 |

**Phase 3 gate: PASS.** Auto-opening Phase 4 (ELIGIBILITY ENGINE &
EXPORTS) per master directive.
