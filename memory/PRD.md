# OpportunityOS — Product Requirements (living)

**Codename in repo:** LYNK.  
**Web-first.** Backend: FastAPI @ 8001. Frontend: React @ 3000. DB: MongoDB. Ingress: all backend under `/api/*`.

## Product law
- Candidate-fiduciary. Consent-first. Every state-changing action is authenticated, idempotent, audited.
- Optimize for **qualified interviews**, never application volume.
- The **Career Passport** (approved claims) is the ONLY factual source of truth. No shadow inference gets written back to it.
- No scraping. No password harvesting. No invented facts. No auto-submit without approval.

## Roles
- `user` (default), `support`, `admin`. Admin/support gated via `admin_users` collection.

## Consent scopes (v1.0)
1. `process_career_data` — required to create an account.
2. `discover_jobs` — optional.
3. `generate_materials` — optional.
4. `track_applications` — optional.
5. `email_me` — optional.

Consent ledger is APPEND-ONLY. Revocation = new row with `granted=false`. No delete/update endpoints, ever.

## Idempotency
Every state-changing endpoint (POST/PUT/PATCH/DELETE under `/api/v1/*`) accepts `Idempotency-Key` header. Middleware caches successful responses per (user, method, path, key) and replays the byte-identical body on retry — no duplicate side effects, no duplicate audit rows.

## Audit
Every state-changing action writes an APPEND-ONLY `audit_logs` row: `{actor, action, object_ref, ts}`.

## Sealed fields
Claims with `sensitivity="sealed"` (e.g., work authorization) serialize as `"•••• (sealed)"` for anyone who is not the owning user — including admin and support.

## Roadmap phases (planning only)
- **Phase 1 (shipped):** Foundation — auth, consent ledger, audit, idempotency, sealed serializer, seed data, premium design shell, gated admin route.
- **Phase 2 (shipped):** Career Passport ingestion & approval flow — resume upload, real LLM parse (gpt-5, fallback gpt-4o), claim lifecycle (approve/reject/edit versioning with `superseded_by`), preferences, eligibility (sealed) + gate engine v0 + coverage preview.
- Phase 3: Jobs feed, discovery, matching (extends gate engine, employer green-lane rules).
- Phase 4: Grounded AI generation (resume tailoring, cover letter). Models: `claude-sonnet-4` for generation + validator. All records write actual model string into `ai_generations`.
- Phase 5: Application tracker, analytics.
- Phase 6: Admin console + billing (Stripe — container `STRIPE_API_KEY` noted).

## Integrations
- **LLM:** `EMERGENT_LLM_KEY` via `emergentintegrations`. Phase 2 wires resume parsing pinned to primary `gpt-5` with automatic fallback to `gpt-4o`. Actual model string is persisted on every parsed claim's `source.model` and on `documents.parse_meta.model_used`.
- **Storage:** local disk at `/app/backend/storage` behind a `StorageService` interface (S3-compatible surface — `s3_key` + `sha256` on `documents`).
- **Email / analytics / error tracking:** internal stubs with preserved interfaces.
- **Background task queue:** `services/queue_stub.py` — asyncio-based, bounded by a semaphore. Swappable for Celery/RQ/SQS later.
- **Anti-virus scan:** honestly labeled `av_status="skipped_v0.1"` on every uploaded document — no AV wired in yet.
- **Billing:** deferred to Phase 6.

## Deviations of record
- Original docs specified Clerk for auth. We deviated to internal JWT + bcrypt to avoid a mandatory external dependency for Phase 1. The auth module is isolated (`domains/auth/*`) and swappable.
