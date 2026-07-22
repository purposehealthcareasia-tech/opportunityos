# Test Credentials — OpportunityOS

> Read by testing agents and fork runs. Keep in sync with `domains/seeds/seeder.py`.

**Preview base URL:** `https://lynk-preview-2.preview.emergentagent.com`

## Auth transport (Phase 6)

- **Browser clients:** cookie-based sessions. `oppos_session` (httpOnly, Secure, SameSite=Lax for user / Strict for admin/support) + `oppos_csrf` (JS-readable, same SameSite). Every POST/PUT/PATCH/DELETE under `/api/v1/*` must echo `X-CSRF-Token` = cookie value.
- **CI / pytest / curl smoke:** Bearer JWT still accepted because `CI_TEST_ISSUER_ENABLED=true` in the preview `.env`. Login response includes `access_token` when that flag is on. Prod builds MUST set `CI_TEST_ISSUER_ENABLED=false`; server refuses to start if `PROD_MODE=true` and the flag is on.
- **Internal endpoints** (`/api/internal/*`) still gated by `X-Service-Token` header, no cookie required.

---

## ⭐ Fixture user — USE THIS FOR AUTOMATED TESTS (Phase 3+)

- **Email:** `fixture-ead@opportunityos.dev`
- **Password:** `Fixture!Test1`
- **Role:** `user`
- **Persona:** Synthetic test fixture. NOT a real candidate.
- **State (re-baselined on every backend startup):**
  - Passport ACTIVATED
  - Consents: ALL 5 scopes granted
  - Eligibility: `status=ead_opt`, opt_end=2027-12-31, earliest_start=2026-03-01 (sealed)
    → derived_flags `{itar_excluded:true, e_verify_need:true, sponsorship_need:true}`
  - Preferences v1: locations `["Phoenix, AZ", "Remote (US)"]`, `remote_ok:true`,
    salary_floor $90,000, role_families incl. vehicle systems + simulation + controls + …
  - Claims (all APPROVED, version 1):
    - identity, contact, location Phoenix AZ US
    - education: MS Mechanical Engineering @ Test University, 2018-08 → 2020-05
    - employment: Fixture Motors Systems Engineer, 2020-08 → present (~5.5 yrs by 2026-02)
    - skills: MATLAB, Simulink, SolidWorks, MBSE, requirements, systems
  - Applications, hidden_jobs, match_scores, usage_meters, documents, resume_versions:
    **wiped on every startup** — start clean.

Deterministic acceptance-check-B against the seeded 15 SampleCo jobs for this user:
- `GET /api/v1/jobs/feed` → passing count **exactly 9**, excluded count **exactly 6**.
- `excluded_by_reason.requires_us_person` **exactly 2** (Autonomy Systems + Fab Equipment).
- `excluded_by_reason.no_sponsorship_offered` **exactly 4** (Battery Test, Battery Thermal, Vehicle Test, Manufacturing Process).
- `GET /api/v1/eligibility/coverage-preview` returns **identical** numbers (gate-engine parity).

### On-demand rebase for CI / persistent tests

If a test suite mutates fixture state between backend restarts, call this BEFORE the run to
guarantee the 9/6 geometry is reachable:

```bash
BASE="https://lynk-preview-2.preview.emergentagent.com"
TOKEN=$(grep INTERNAL_SERVICE_TOKEN /app/backend/.env | cut -d= -f2)
curl -s -X POST "$BASE/api/internal/fixture/rebase" \
  -H "X-Service-Token: $TOKEN"
```

Response `{"ok":true, "fixture_user_id":"…"}`. Same 401/403/503 semantics as
`/api/internal/jobs/bulk`. Never mention or log the token value.

The endpoint fully re-baselines fixture-ead@ (wipes applications, hidden_jobs,
match_scores, usage_meters, score_feedback, documents, resume_versions, claims,
consent_records) and restores passport-activated + all consents + eligibility=ead_opt
sealed + prefs Phoenix+Remote+$90k floor + approved claims.

---

## User Zero (real seed candidate — DO NOT use for destructive tests)

- **Email:** `ujjwal@opportunityos.dev`
- **Password:** `Passport!Test0`
- **Role:** `user`
- **Persona:** Ujjwal Singla — Phoenix, AZ — automotive systems engineer
- **⚠️ Reserved for demos and product-owner walkthroughs.** Do NOT run automated tests
  that mutate his preferences / eligibility / applications. Use `fixture-ead@` above.
- **One-time cleanup (marker `user_zero_cleanup_v1`) removes tester pollution:**
  preferences, eligibility_profiles, applications, hidden_jobs, match_scores,
  usage_meters, documents, resume_versions, score_feedback. Claims + consent_records +
  audit_logs are preserved (append-only rule).

## Admin
- **Email:** `admin@opportunityos.dev`
- **Password:** `Admin!Console1`
- **Role:** `admin`

## Support
- **Email:** `support@opportunityos.dev`
- **Password:** `Support!Console1`
- **Role:** `support`

---

## Google Sign-In (Milestone E)

- The Emergent-managed OAuth flow requires a browser to click "Continue with
  Google" on `/login` or `/signup` and complete a Google consent screen.
  There is NO password fixture for this path.
- For automated backend tests, `domains/auth/google_service.py` accepts
  a session_id and calls `https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data`.
  Tests stub this call via `httpx.MockTransport` (see
  `tests/test_milestone_e_google.py`).
- Any real end-to-end validation requires a HUMAN with a Google account
  clicking the button — mark as `HUMAN_REQUIRED` in test plans.

## Sign in with Apple (2026-02-21)

- Standards-based OIDC. Preview status is **CONFIGURATION_REQUIRED** —
  frontend renders a disabled "Continue with Apple — not yet available"
  button + tooltip explaining the state.
- Backend tests use mocked id_tokens (`tests/test_auth_apple_signin.py`),
  full JWKS-verify path exercised via a locally generated P-256 keypair
  and a stubbed httpx client. No real Apple endpoint calls in tests.
- Real click-through requires HUMAN with an Apple ID once the founder
  provisions `APPLE_CLIENT_ID`, `APPLE_TEAM_ID`, `APPLE_KEY_ID`,
  `APPLE_PRIVATE_KEY`, and `APPLE_REDIRECT_URI`.

## Phone OTP login (Twilio Verify, 2026-02-21)

- Login-only flow: a user with an attached phone gets a code and signs in.
- Preview status is **CONFIGURATION_REQUIRED** — frontend Phone tab shows
  "Phone sign-in is not yet configured on this server. Use email or
  Google/Apple sign-in for now." No fake Send-code button.
- Backend tests mock `start_verify` / `check_verify` on the Twilio provider
  (`tests/test_auth_otp_login.py`). No real SMS is ever sent by the suite.

## Web Push notifications (2026-02-21)

- Standards-based VAPID. Preview status is **CONNECTED** — the VAPID key
  pair was generated once via `py_vapid` and lives in `backend/.env`
  (`VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT`).
- **DO NOT** regenerate these keys casually on deploy — regeneration
  invalidates every existing browser subscription. Set once in prod
  secrets and leave it alone.
- Automated tests (`tests/test_notifications_webpush.py`) mock `pywebpush`
  and never actually send a push. Real delivery requires a browser to
  subscribe first — mark as `HUMAN_REQUIRED` in test plans.

---

## Curl smoke test

```bash
BASE="https://lynk-preview-2.preview.emergentagent.com"
# Fixture user login
curl -s -X POST "$BASE/api/v1/auth/login" \
  -H 'Content-Type: application/json' \
  -d '{"email":"fixture-ead@opportunityos.dev","password":"Fixture!Test1"}'
```
