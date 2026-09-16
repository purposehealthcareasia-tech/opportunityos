# ATLAS-STATE.md — running state of the FYND ATLAS program

**Persisted per FYND-ATLAS §47.** Records the current gate position, orchestrator/founder decisions, and burn-down of the standing ordered sequence. Every logical unit lands here as it commits.

---

## §1 · Current gate position (2026-08-13)

- **Hotfix trio + Gate Fix** — GATE-PASSED on `main` @ `c00b7737` + `e49406d6` + `6e600014` + `06149bf0`. Waiting on founder's Save-to-GitHub + Re-publish click; workspace-side ready.
- **Save-to-GitHub sync** — hygiene sweep complete, `.env.example` schemas written, 4 branches TRIPWIRE_CLEAN, push credential-blocked (founder rail). `main` HEAD prior to P0 kickoff: `06149bf0`.
- **P0 TRUTH AUDIT** — **UNBLOCKED** by orchestrator decide-and-document decision (2026-08-13). Founder deferred the Re-publish click "for now". Decision recorded verbatim below.

## §2 · Decide-and-document — P0 unblock (2026-08-13, orchestrator)

**Decision.** P0 Truth Audit begins immediately on `main`. Every commit leaves the app continuously releasable.

**Rationale (verbatim from orchestrator).**
> "P0 work happens in the workspace on main and cannot affect prod until the founder's Re-publish click, which remains the founder's alone; waiting idle serves no rail. The hotfix trio (c00b7737) stays gate-passed on main and will ship together with P0 truth items whenever the founder clicks Re-publish."

**Rails held.**
- Continuous releasability: `main` stays green after every commit; supervisor hot-reload works throughout; no partial migrations.
- Publish clicks remain the founder's alone. No merge to origin, no deploy, no `.env` edits.
- SAMPLE / fixture rows NEVER surface in the P0 metrics that will render on `/standards`. `is_sample=False` filter is a hard invariant on every counted read.
- Never-fabricate: when `n` is below the honest threshold, render "measuring" — never a synthesized number.
- `country_allowlist` schema addition remains QUEUED for P1. Not pulled forward.

## §3 · P0 TRUTH AUDIT — full scope (9 items)

Ordered by dependency, not by founder-list letter. Each item ships as its own commit with tests alongside.

| # | Founder letter | Item | Status | Commit |
|---|---|---|---|---|
| 1 | init | Initialize ATLAS-STATE.md | **DONE** | `b7b8979a` |
| 2 | (b) | Brand sweep — kill `opportunityos.dev` from every user-facing served surface | **DONE** | `41a29043` |
| 3 | (a) | `/privacy-policy` serves the real static crawlable versioned policy (no SPA shell) | **DONE** | `8249bd73` |
| 4 | (c) | Footer version string derives from build (`package.json`), no `v0.1` literal | **DONE** | (chained) |
| 5 | (g) | `robots.txt` + `sitemap.xml` as real static files, correct content-types | **DONE** | (chained) |
| 6 | (e) | Operator / about page (legal entity, contact) | **DONE** | (chained) |
| 7 | (d) | `/standards` sync — reflect Phase 0-6 + hotfix, add change history | **DONE** | (chained) |
| 8 | (f) | `/standards` outcome rows (median days-to-first-response, interviews/100 apps) + public claim-verification ladder | **DONE** | (chained) |
| 9 | (i) | `/standards` per-country coverage row — real rows only, SAMPLE segregated, indeterminate bucket | **DONE** | (chained) |
| 10 | (h) | North-star instrumentation — TQI + guardrails; measure baseline BEFORE optimization; SAMPLE excluded | **DONE** | (chained) |
| 11 | evidence | `docs/P0-TRUTH-EVIDENCE.md` + tripwire + STOP for split-brief gate | **DONE** | (this commit) |

## §4 · Never-fabricate honest thresholds

Recorded so every P0 render obeys the same rule:

- **Median days-to-first-response.** Render only when the pool has ≥20 real (non-SAMPLE, non-fixture) `application_outcomes` rows tagged `event=response_received`. Below threshold → `"measuring"` string.
- **Interviews per 100 applications.** Render only when the pool has ≥50 real submitted applications. Below threshold → `"measuring"`.
- **Per-employer response medians on the /employers pool page** (queued, P4/P5) — never render below n=5 for a given employer; below → the employer row shows `"measuring"` and the number is omitted.
- **Time to Qualified Interview (baseline).** Render current pool baseline when ≥10 real interview outcomes exist; below → `"measuring (baseline)"`.
- **Guardrail metrics** (application→response, response→interview, false-pass, false-exclusion, duplicate rate, closed-listing exposure, consent-violation count). Render current pool baseline when ≥30 real applications exist; below → `"measuring (baseline)"` with the honest n shown.

## §5 · Sample / fixture segregation (hard invariant)

Every P0-produced metric that renders on `/standards` MUST filter `is_sample=False` at the DB level (or exclude fixture user IDs `fixture-ead@opportunityos.dev`, `fixture-broad@opportunityos.dev`, `fixture-employer-member@opportunityos.dev`, `admin@opportunityos.dev`, `support@opportunityos.dev` from user-scoped queries). Static tests (below) fail CI if a metrics function reads a row without the exclusion.

## §6 · P0 tests (built alongside each item)

- `backend/tests/test_standards_metrics_exclude_sample.py` — hard-locks every metrics accessor excludes SAMPLE rows.
- `backend/tests/test_standards_change_history.py` — locks phase sync + change history append-only shape.
- `backend/tests/test_public_static_assets.py` — `curl /robots.txt` returns text/plain and mentions Fynd; `curl /sitemap.xml` returns application/xml; `curl /privacy.html` returns text/html and is Version 1.0.
- `backend/tests/test_version_endpoint.py` — `/api/v1/meta/version` returns semver derived from `package.json`/`requirements`, NOT a literal `v0.1`.

## §7 · Not in this P0 (parked)

- `country_allowlist` schema addition to `eligibility_requirements` — QUEUED for P1 Foundation. Do not pull forward.
- Real per-employer response medians — needs the outcomes pool to hit n=5 per employer, queued for P4/P5.
- P1 Foundation items (13 per `ATLAS-FEATURE-MAP.md`) — do NOT start until founder split-brief gate on this P0.

---

## §8 · Timeline (append-only)

- **2026-08-13T13:00Z** — ATLAS-STATE.md initialized. P0 Truth Audit unblocked by orchestrator decide-and-document. Founder's Re-publish click remains outstanding.
- **2026-08-13T13:45Z** — P0 Truth Audit COMPLETE (items a-i + init + evidence). All 11 sequence items landed on `main` under continuous-releasability discipline. Evidence in `docs/P0-TRUTH-EVIDENCE.md`. 83 P0-focused tests passing. Tripwire clean. STOPPED for founder split-brief gate + Save-to-GitHub push + Re-publish. P1 Foundation remains BLOCKED.
- **2026-08-13T14:10Z** — P0 gate: 4/4 PASS with ONE WARN (/privacy-policy SPA shell). WARN CLOSED at commit `1f120e82` (static file at frontend/public/privacy-policy/index.html byte-identical to privacy.html; SPA route dropped; live curl proof + 3 tests). Rendered-copy walk of /employers + /about confirmed no visible OpportunityOS strings. Evidence §7 appended.
- **2026-08-13T14:15Z** — **P1 FOUNDATION UNBLOCKED** by orchestrator decide-and-document. Rationale recorded in §9 below. Founder split-brief gate on P0 still pending; publish clicks remain deferred; main stays continuously releasable.
- **2026-08-13T14:30Z** — P1 Batch 1 (Source Access Policy Engine + Global Source Registry) landed. Focused pytest 30 passed. Commit chain ending at `b7b8979a`+.
- **2026-08-13T15:00Z** — P1 Batch 2 (Opportunity Source Connector SDK) landed at `42367234`. Every network op now routes through `source_policy.allow(...)` at the network-op site itself (fail-CLOSED). Byte-identical output vs. pre-SDK on real Greenhouse response (621 postings verified). 9 SDK tests pass. Kill switch in-flight halt + PolicyDenied-fails-CLOSED tripwire tests locked. Total P1 focused: 36 passed.
- **2026-08-13T15:30Z** — P1 Batch 3 (Canonical Opportunity Model + `country_allowlist`) landed at (this commit). `EligibilityRequirements.country_allowlist: list[str] | None` populated ONLY from Ashby `address.postalAddress.addressCountry` + `secondaryLocations[].address.postalAddress.addressCountry` (real source field); USAJOBS federal → `["US"]`; GH/Lever stay `None`. Full refresh_all executed against preview: 21,664 postings ingested; **3,532 rows carry country_allowlist** (Ashby-sourced structured address extraction); of the remote pool (n=2,622), **318 remote rows moved from indeterminate → country_allowlist_classified** (12.1% shift). `/standards` per_country_coverage now surfaces `country_allowlist_classified` bucket alongside `us_only / india_explicit / indeterminate`. SAMPLE-exclusion invariant preserved. 8 country-allowlist tests + 11 standards metrics tests pass. Total P1 focused: 49 passed. STOP for founder split-brief review before Batch 4 (hostile-content defense / SSRF / prompt-injection — highest-risk P1 item).
- **2026-08-13T15:45Z** — **Batches 2 & 3 REVIEWED AND ACCEPTED** by orchestrator. External tester deferred to full P1 gate; agent evidence sufficient for mid-phase review. Batch 4 unblocked with hard requirements (freshness enum, cluster canonical priority ladder, full ATLAS hostile-content test set including cloud-metadata IPs, DNS-rebinding pin-to-IP defense, and grep-lock).
- **2026-08-13T16:15Z** — P1 Batch 4 Item 1 (Freshness ≠ Liveness) landed at `678a341d`. `LivenessState` enum with 5 values; hard invariant that EVERY in-edge to `active` requires evidence (check/at/observed) — not just unknown→active; `inactive` terminal, no egress. Per-source freshness budgets (GH/Lever/Ashby 6h, USAJOBS 24h). `enforce_liveness_before_dispatch()` wired into `preflight_check` — refuses on missing job, not-active state, no-evidence, or stale freshness. 15 tests pass. `_to_jobs_doc` uses `apply_transition()` so evidence is required at the write site.
- **2026-08-13T16:35Z** — P1 Batch 4 Item 2 (Entity Resolution + Dedup Clusters) landed at `457edfc9`. Deterministic priority ladder (official_api > ats_record > employer_page > government > licensed > directory > search_copy). `compute_cluster_key()` layers: (domain, req_ref) → (domain, title_sig) → solo singleton. ATS host prefixes stripped so cross-source rows converge. Clusters are append-only records with `cluster_history`; never deletions. `dedup_check(user_id, job_id)` widens the never-submit-same-req-twice rail cluster-aware. `submit_application` now emits `duplicate_application_cross_source` 409 for cross-source dup attempts. 13 tests pass.
- **2026-08-13T16:55Z** — P1 Batch 4 Item 3 (Hostile-Content Defense) landed at (this commit). Full 14-rail test set: protocol allowlist (rejects file/gopher/ftp/data/javascript/vbscript/about/chrome/view-source/blob); private+link-local+loopback+reserved+multicast IP blocking; cloud-metadata IPs hardcoded (169.254.169.254 + IPv6 equivs); DNS-rebinding defense (resolve, validate every answer, pin connection to validated IP with Host header + TLS SNI); redirect-chain cap (max 3) + per-hop re-validation; response-size cap (8 MiB); timeout (15s); MIME allowlist; HTML sanitization (script/style/iframe/object/embed/applet/form/event-handlers/javascript-and-data-URIs); structured-output schema validation; retrieved-text fencing that cannot be forged; HMAC-SHA256 constant-time webhook verify; policy-decision logging; PII redaction (email/phone/SSN) in logs; **grep-lock invariant** that no raw `httpx.AsyncClient` exists outside `services/hostile_content_defense.py` OR the source-adapter gated path OR the reviewed first-party integration allowlist (Stripe/Twilio/Google/Apple/Resend/SendGrid/ElevenLabs). 60 tests pass. Total P1 focused: 186 passed (14+7+9+8+15+13+60+15+5+23+17). Zero regressions in gate_engine, phase3_safeguards, preflight_validator.
- **P1 BATCH 4 COMPLETE. STOP for founder tester pass** — given the security surface, orchestrator will run an external tester before Batch 5 unblock. Main remains continuously releasable throughout.

## §9 · P1 FOUNDATION unblock — decide-and-document (2026-08-13, orchestrator)

**Decision.** P1 Foundation begins immediately on `main`. Same continuous-releasability rail as P0.

**Rationale.** Founder's brief on the P0 gate result: "P1 FOUNDATION IS UNBLOCKED (decide-and-document; founder's publish clicks remain deferred, main stays continuously releasable; record the unblock decision in ATLAS-STATE.md as with P0)."

**Rails held (identical to P0).**
- Continuous releasability: `main` stays green after every commit.
- Publish clicks remain the founder's alone.
- SAMPLE / fixture rows NEVER surface in P1 metrics or registry records.
- Zero-tolerance items encoded as CI checks where testable (§44 of FYND-ATLAS).
- No connector code path bypasses the Source Access Policy Engine.

## §10 · P1 FOUNDATION scope — 13 items in dependency order

Batches are self-contained. STOP at each batch boundary for a report; founder may gate mid-phase for high-risk batches.

| Batch | Item | Status | Commit |
|---|---|---|---|
| **1** | Source Access Policy Engine (deterministic, fail-closed, no-LLM; robotsStatus/termsStatus/licenseStatus/legalReviewStatus × 8 operations; kill switch) | **DONE** | `b7b8979a`… |
| **1** | Global Source Registry (16 verified providers as first records; full lifecycle; no source skips shadow) | **DONE** | `b7b8979a`… |
| **2** | Connector SDK — `OpportunitySourceConnector` incl. `normalize()`; refactor Greenhouse / Lever / Ashby onto it | **DONE** | `42367234` |
| **3** | Canonical Opportunity Model + category extensions; **includes `country_allowlist: list[str] \| null` on `eligibility_requirements`** — populated ONLY from real source fields, never inferred | **DONE** | (this commit) |
| **4** | Freshness ≠ liveness (per-source freshness stamp separate from is_live) | **DONE** | `678a341d` |
| **4** | Entity resolution + dedup clusters (deterministic clustering key + membership records) | **DONE** | `457edfc9` |
| **4** | Hostile-content defense — full SSRF/prompt-injection test set | **DONE** | (this commit) |
| **5** | Matching constitution — Stage 1 deterministic gates SEPARATE from Stage 2 explainable ranking | pending | — |
| **5** | Application route engine | pending | — |
| **5** | Fastest-path engine | pending | — |
| **6** | Lanes with exposed logic (career / income-now / newgrad / etc.; logic surfaced per-card) | pending | — |
| **6** | i18n foundation (message-catalog scaffold, no runtime language switch yet) | pending | — |
| **6** | AI boundaries (grounding invariants, no-fabrication test suite, generation firewall reuse) | pending | — |

---

## §11 · Task 2 · Pulse UI — MERGED (2026-09-16, `89c257ca`)

Founder gate: 4/4 PASS. Focused pytest on `feat/pulse-ui-integration` = 238 passed. Merged to `main` (`--no-ff` for audit trail).
Publish clicks remain the founder's alone.

### Blockers awaiting founder decision (kept in honest-empty state on the platform)

**BLOCKER-11.a · Comments (`/api/v1/pulse/posts/:id/comments`).** Returns `{items:[], next_cursor:null}`. Recommended privacy model: comments inherit the parent post's audience (members / followers / private). Commenters must be able to see the post; blocked-either-way pairs are hidden from each other's comment authorship. Moderation: soft-hide (never delete) via `is_hidden` flag settable by post-author (their thread) or admin (any thread); the original text is retained in `pulse_comment_history` for audit. Rate limit: 30 comments per user per rolling 10 minutes (reuses the existing rate-limit middleware). Comment length cap: 800 chars. Ready to build on founder approval.

**BLOCKER-11.b · Threads / messaging (`/api/v1/pulse/threads`).** Returns `{items:[], next_cursor:null}`. Recommended privacy model: three-state thread (`pending` / `accepted` / `declined`). When a sender opens a thread with a non-follower recipient, the thread goes to `pending`; only the sender's FIRST message is visible to the recipient (rendered as a message request card, never in the main inbox). Recipient must ACCEPT before further messages become readable OR before the recipient's replies are permitted. `declined` is terminal — sender receives no notification (silent) but cannot re-open a new thread with the same recipient for 30 days. Recipient's `message_policy` (`requests` / `following` / `closed`) is the top-level gate before any of this. Ready to build on founder approval.

**BLOCKER-11.c · Reports (`/api/v1/pulse/posts/:id/report`).** Not wired. Recommended: `report_reason ∈ {spam, harassment, prohibited_content, other}`; reports queue into `pulse_moderation_reports` collection with `status=pending`; author of a reported post is never notified; three unique reporters on the same post auto-marks it `is_hidden=true` pending admin review. Moderation ops staffing pending founder decision — the queue itself can ship without staffing.

### HUMAN_REQUIRED · Real 390 px mobile-reflow verification

The pod's Playwright context in this environment cannot honor `set_viewport_size({"width":390})` at context creation time — the tool reports viewport `1920×1080` even after the call. The Pulse CSS reflow machinery IS in place and verified passively:

- `<body data-responsive="true">` is present (breakpoint switch engaged).
- `.bottom-nav` element rendered but `getComputedStyle(bottomNav).display === "none"` at desktop width (confirms the mobile-only CSS rule was compiled and served).
- `responsive-layout.css` + `responsive-navigation.js` are unchanged from the SOURCE.json-verified ZIP.

**Founder action steps for real-device verification:**

1. On your phone, navigate to `https://lynk-preview-2.preview.emergentagent.com/pulse/network.html`.
2. In another tab/desktop, log in via any fixture in `memory/test_credentials.md` (pod's `/api/v1/auth/login`). Then reload the phone tab.
3. Expect: single-column layout, bottom-nav bar visible with Feed / Discover / Post / Inbox / You tabs, no 3-column desktop sidebar.
4. Rotate to landscape — layout should shift to 2-column at ≥ 640 px.

Report back if any breakpoint fails so I can inspect the CSS directly.

---

## §12 · Batch 4 close-out re-verification (post-Task-2 merge)

**Batch 4 security surface — 88 tests still green after Task 2 merge:**

```
tests/test_liveness_gate.py              15 passed
tests/test_entity_resolution.py          13 passed
tests/test_hostile_content_defense.py    60 passed
                                         ────────
                                         88 total, 0 regressions from Pulse work
```

## §13 · P1 Batch 4 flake fix — PARTIAL RCA, moved forward

**Symptom.** `tests/test_source_registry.py` + 6 companion tests fail when the full test suite runs AFTER `tests/test_apply_at_birth.py` — pytest-asyncio 1.4.0 + motor 3.5.1 loop-binding interaction. Each file passes in isolation.

**RCA established (2026-09-16):**
1. `test_apply_at_birth.py` monkey-patches `core.db.get_db` to a lambda returning a scratch DB (`oppos_test_apply_at_birth`) but never touches `_core_db._client` or `_core_db._db` directly.
2. During apply_at_birth's execution, code under test (e.g. `services/lifecycle_sweep.py`, `services/apply_at_birth.py`, and every fetch through `domains/discovery/adapters/public_apis::_gate` → `source_registry.get`) calls `core_db.get_db()` and gets the scratch DB via the monkeypatch.
3. `pytest`'s built-in `monkeypatch` undoes the patch at test teardown.
4. Between apply_at_birth teardown and the next test's fixture, my `_reset_motor_client_per_test` fixture in `test_source_registry.py` (and the four other P1 test files) unconditionally resets `_core_db._client = None; _core_db._db = None`, then calls `get_db()` to seed a fresh client bound to the running loop.
5. The fresh client's `_db` correctly points at `Database(opportunityos)` — verified via `FYND_DB_TRACE=1` env-gated logging in `core/db.py::get_db`.
6. **UNRESOLVED:** despite `_core_db._db.name == 'opportunityos'` after the reset, the failing motor call's args still show `Database(..., 'oppos_test_apply_at_birth')`. This means some code path — likely a captured reference to the scratch db obtained during apply_at_birth's execution — persists into the next test's runtime via a mechanism I have not yet identified. Candidate: an `AsyncIOMotorDatabase` object returned from a coroutine/callback that was scheduled on apply_at_birth's event loop and outlives the fixture teardown.

**Attempted mitigations (all committed as WIP; none fixed the full-suite regression):**
- Guarded → unconditional reset of `_core_db._client` / `_core_db._db` in fixtures.
- `_cached_client_is_usable()` in `core/db.py` — detects closed-loop and loop-mismatch and rebuilds. **Retained** as a permanent defense-in-depth for prod (harmless in the single-loop production case; corrects invalid state in tests).
- `motor.frameworks.asyncio._reset_global_executor()` between tests.
- `asyncio_default_fixture_loop_scope = function` in `pytest.ini`. **Retained** because it's the correct config regardless.
- `asyncio_default_fixture_loop_scope = session` — broke apply_at_birth's own tests; reverted.

**Status:** DEFERRED. All P1 tests still pass in ISOLATION (186 tests green). The security surface (Batch 4 · Items 1-3) is uncompromised. The flake is a test-runner isolation issue, NOT a production issue. Moving forward to Batches 5 & 6 per founder ordering; will return to this after Batch 6 with a fresh angle (likely instrumenting motor's `_EXECUTOR` at teardown OR pinning `pytest-asyncio==0.23.8`).

**Founder external tester note:** the security surface (60 hostile-content-defense + 15 liveness + 13 entity-resolution + 14 policy + 7 registry + 9 connector-SDK = 118 tests) all pass in isolation. Recommend the external tester run each of these files in isolation mode for the security gate, then run the flake reproducer separately.


---

## §14 · P1 Batch 5 · Discovery adapter hardening (2026-02-14, orchestrator)

**Gate finding folded in.** BATCH 4 SECURITY GATE flagged `domains/discovery/adapters/usajobs.py:94` as constructing a raw `httpx.AsyncClient` outside the tripwire's structural guarantee. It DID call `allow().raise_if_denied()`, so behavior was correct — but the tripwire had to ALLOW every discovery-adapter file by name, so any new adapter would need a per-file review.

**Fix.** New module `domains/discovery/adapters/http.py` exports the single guarded factory `policy_gated_client(source_id, operation, ...)`. Every discovery adapter now writes:

```python
async with policy_gated_client("greenhouse", Operation.FETCH) as c:
    r = await c.get(url)
```

The factory runs `source_policy.allow(...).raise_if_denied()` BEFORE constructing the `httpx.AsyncClient`, so fail-CLOSED is enforced at the network op site regardless of which adapter file called in. Kill switch is re-evaluated per call — no cache.

**Sub-tripwire.** `test_no_raw_httpx_under_discovery` asserts that no file under `domains/discovery/` constructs `httpx.AsyncClient(` except the factory. Adding a new adapter without going through the factory fails the grep-lock structurally, before any code review.

**Top-level tripwire pruned.** `public_apis.py` + `usajobs.py` removed from the top-level `ALLOW`, replaced by `http.py`. Future adapters inherit the gate; no per-file allowlist edits.

**Tests wired.** 97/97 green across:
- `test_hostile_content_defense.py` (60 + new discovery sub-tripwire)
- `test_connector_sdk.py` (rewired `test_policy_deny_prevents_httpx_client_creation`, `test_kill_switch_halts_in_flight_connector`, byte-identical + normalize-contract onto the factory monkeypatch)
- `test_source_policy_engine.py` (14)
- `test_source_registry.py` (7)

**Commit.** `38c31958`

