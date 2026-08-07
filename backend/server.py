import logging
from collections import Counter
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from core.config import settings
from core.db import ensure_indexes, get_db
from core.policy import CONSENT_SCOPES, policy_version
from core.sessions import ensure_session_indexes
from services.login_throttle import ensure_indexes as ensure_throttle_indexes
from domains.auth.google_service import ensure_indexes as ensure_google_indexes
from domains.auth.apple_service import ensure_indexes as ensure_apple_indexes
from domains.auth.otp_service import ensure_indexes as ensure_otp_indexes
from integrations import registry as integration_registry
from integrations.health import ensure_indexes as ensure_integration_indexes, snapshot_provider
from routers.integrations import router as integrations_router
from routers.webhooks_email import router as email_webhook_router
from routers.webhooks_payment import router as payment_webhook_router
from domains.notifications.router import router as notifications_router
from domains.notifications.service import ensure_indexes as ensure_notifications_indexes
from domains.notifications.sweep import sweep_forever as notifications_sweep_forever
from middleware.idempotency import IdempotencyMiddleware
from middleware.csrf import CSRFMiddleware
from domains.auth.router import router as auth_router
from domains.consent.router import router as consent_router
from domains.users.router import router as users_router
from domains.passport.router import router as passport_router
from domains.documents.router import router as documents_router
from domains.claims.router import router as claims_router
from domains.preferences.router import router as preferences_router
from domains.eligibility.router import router as eligibility_router
from domains.jobs.router import router as jobs_router
from domains.jobs.internal_router import router as jobs_internal_router
from domains.fixtures.internal_router import router as fixture_internal_router
from domains.admin.bootstrap_internal_router import router as admin_bootstrap_internal_router
from domains.applications.router import router as applications_router
from domains.match_scores.router import router as matches_router
from domains.usage_meters.router import router as usage_router
from domains.screening_answers.router import router as screeners_router
from domains.outcomes.service import router as outcomes_router
from domains.outcomes.intelligence import router as outcomes_intel_router
from domains.supply.service import router as supply_router
from domains.subscriptions.service import router as subscriptions_router
from domains.inbound.internal_router import router as inbound_internal_router
from domains.analytics.service import router as analytics_router
from domains.billing.service import router as billing_router, webhook_router as billing_webhook_router
from domains.privacy.service import router as privacy_router, sweep_expired_deletions
from domains.admin.service import router as admin_router
from domains.support.service import router as support_router
from domains.observability.service import router as observability_router
from domains.seeds.seeder import run_seeds

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("oppos")


# ---------------------------------------------------------------------------
# Fail-fast: PROD_MODE + CI_TEST_ISSUER_ENABLED must never both be true.
# The CI-only Bearer issuer is a testing shim; it MUST be disabled in prod.
# ---------------------------------------------------------------------------
if settings.PROD_MODE and settings.CI_TEST_ISSUER_ENABLED:
    raise RuntimeError(
        "SECURITY: CI_TEST_ISSUER_ENABLED cannot be true in PROD_MODE=true. "
        "Disable one before starting the server."
    )


def _assert_unique_operation_ids(app_: FastAPI) -> None:
    """Guard against silent route collisions (founder amendment 1). Any
    duplicate FastAPI operation_id crashes startup with a listing so the bug
    can never recur unnoticed."""
    op_ids: list[str] = []
    for route in app_.routes:
        opid = getattr(route, "operation_id", None) or getattr(route, "name", None)
        path = getattr(route, "path", "?")
        methods = getattr(route, "methods", set()) or set()
        # Skip mount / WebSocket / static.
        if not methods or {"HEAD"} == methods:
            continue
        for m in sorted(methods - {"HEAD"}):
            op_ids.append(f"{m} {path}::{opid}")
    dupes = [k for k, v in Counter(op_ids).items() if v > 1]
    if dupes:
        raise RuntimeError(
            "Duplicate FastAPI operation IDs detected:\n  - "
            + "\n  - ".join(dupes)
        )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    log.info("Fynd backend starting…")
    await ensure_indexes()
    await ensure_session_indexes()
    await ensure_throttle_indexes()
    await ensure_google_indexes()
    await ensure_apple_indexes()
    await ensure_otp_indexes()
    await ensure_integration_indexes()
    await ensure_notifications_indexes()
    # Load and snapshot every provider so the admin dashboard shows real status
    # immediately on first request.
    integration_registry.load_all()
    for _p in integration_registry.all_providers():
        try:
            await snapshot_provider(_p)
        except Exception:
            log.exception("Failed to snapshot integration provider %s", _p.slug)
    _assert_unique_operation_ids(_app)
    try:
        counts = await run_seeds()
        log.info("Seed complete: %s", counts)
    except Exception:
        log.exception("Seeder failed")
    try:
        swept = await sweep_expired_deletions()
        if swept:
            log.info("Deletion sweep hard-deleted %d user(s).", swept)
    except Exception:
        log.exception("Deletion sweep failed")
    # Kick off the approvals-expiring push sweep (runs every 30 min).
    import asyncio
    _sweep_task = asyncio.create_task(notifications_sweep_forever())
    # Discovery scheduler (6h) — pulls real jobs from Greenhouse/Lever/Ashby.
    try:
        from domains.discovery.scheduler import start_scheduler as _disc_start
        _disc_start()
    except Exception:
        log.exception("discovery scheduler start failed")
    try:
        yield
    finally:
        _sweep_task.cancel()
        try:
            await _sweep_task
        except (Exception, asyncio.CancelledError):
            pass
        try:
            from domains.discovery.scheduler import stop_scheduler as _disc_stop
            _disc_stop()
        except Exception:
            pass
    log.info("Fynd backend shutting down…")


app = FastAPI(
    title="Fynd API",
    version="0.1.0",
    openapi_url="/api/openapi.json",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS — explicit allowlist required for credentialed requests (cookies).
# SEC-004(b): in PROD_MODE the allowlist is used AS-IS from CORS_ALLOW_ORIGINS.
# Loopback origins (localhost / 127.0.0.1) are stripped so a misconfigured env
# var can't accidentally trust a dev client from production. In non-prod they
# remain allowed so the dev browser session works.
# ---------------------------------------------------------------------------
_raw_origins = [o.strip() for o in (settings.CORS_ALLOW_ORIGINS or "").split(",") if o.strip()]
if settings.PROD_MODE:
    _origins = [o for o in _raw_origins
                if "localhost" not in o and "127.0.0.1" not in o]
else:
    _origins = _raw_origins
if _origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*", settings.CSRF_HEADER_NAME, "X-Service-Token", "Idempotency-Key"],
        expose_headers=["X-Idempotent-Replay"],
    )
else:
    # Dev fallback — no credentials because wildcard + credentials is illegal.
    # In PROD_MODE with an empty allowlist we refuse to start (fail-fast): a
    # production deploy without a CORS allowlist is a footgun.
    if settings.PROD_MODE:
        raise RuntimeError(
            "SEC-004: PROD_MODE=true requires a non-empty CORS_ALLOW_ORIGINS. "
            "Set the env var to the exact production origin(s) before starting."
        )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Idempotent-Replay"],
    )

app.add_middleware(IdempotencyMiddleware)
app.add_middleware(CSRFMiddleware)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    log.exception("Unhandled: %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "internal_error"})


# SEC-004(e): FastAPI's default 422 handler echoes the raw request body
# under `detail[].input`. That leaks plaintext credentials whenever a
# malformed signup / login / reset payload triggers Pydantic validation.
# This handler scrubs a fixed denylist of sensitive keys from every `input`
# value before serialisation. Non-sensitive keys, error types, error msgs
# and locations are preserved so callers can still debug their payloads.
_VALIDATION_SCRUB_KEYS = frozenset({
    "password", "password_hash", "token", "otp",
    "code", "session_id", "refresh_token",
})


def _scrub_input(value):
    """Recursively remove sensitive keys from a validation `input` payload."""
    if isinstance(value, dict):
        return {
            k: ("<redacted>" if k in _VALIDATION_SCRUB_KEYS else _scrub_input(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_scrub_input(item) for item in value]
    return value


@app.exception_handler(RequestValidationError)
async def scrub_validation_error(request: Request, exc: RequestValidationError):
    """422 handler that never lets a submitted password, token, otp code,
    session id or refresh token leak back to the caller inside the error
    body. Preserves loc / msg / type so schema debugging still works.

    2026-08-06 fix: pydantic v2 sometimes stuffs a raw `Exception` object
    into `err["ctx"]["error"]` (e.g. when a `@field_validator` raises
    ValueError). That is not JSON-serializable and blew up the response
    render as a 500. We now coerce `ctx` values to their string
    representation so the loc/msg is preserved but the exception object
    never reaches `json.dumps`.
    """
    def _safe_ctx(ctx: object) -> object:
        if not isinstance(ctx, dict):
            return str(ctx)
        return {k: (v if isinstance(v, (str, int, float, bool, type(None)))
                     else str(v)) for k, v in ctx.items()}

    scrubbed = []
    for err in exc.errors():
        item = {
            "type": err.get("type"),
            "loc": err.get("loc"),
            "msg": err.get("msg"),
        }
        if "input" in err:
            item["input"] = _scrub_input(err.get("input"))
        if "ctx" in err:
            item["ctx"] = _safe_ctx(err.get("ctx"))
        scrubbed.append(item)
    return JSONResponse(status_code=422, content={"detail": scrubbed})


@app.get("/api/health", tags=["meta"])
async def health():
    """Public health probe — SEC-004(d): deliberately does NOT disclose the
    server's PROD_MODE / CI_TEST_ISSUER_ENABLED flags. Those live behind the
    admin health endpoint (`/api/v1/admin/health`) instead."""
    db = get_db()
    try:
        await db.command("ping")
        mongo_ok = True
    except Exception:
        mongo_ok = False
    return {
        "ok": True,
        "mongo": mongo_ok,
        "phase": 6,
        "policy_text_version": policy_version(),
    }


@app.get("/api/v1/meta/policy", tags=["meta"])
async def policy_meta():
    """Public policy metadata used by the signup screen."""
    return {
        "policy_text_version": policy_version(),
        "scopes": CONSENT_SCOPES,
    }


app.include_router(auth_router)
app.include_router(consent_router)
app.include_router(users_router)
app.include_router(passport_router)
app.include_router(documents_router)
app.include_router(claims_router)
app.include_router(preferences_router)
app.include_router(eligibility_router)
app.include_router(jobs_router)
app.include_router(jobs_internal_router)
app.include_router(fixture_internal_router)
app.include_router(admin_bootstrap_internal_router)
app.include_router(applications_router)
app.include_router(matches_router)
app.include_router(usage_router)
app.include_router(screeners_router)
app.include_router(outcomes_router)
app.include_router(outcomes_intel_router)
app.include_router(supply_router)
app.include_router(subscriptions_router)
app.include_router(inbound_internal_router)
app.include_router(analytics_router)
app.include_router(billing_router)
app.include_router(billing_webhook_router)
app.include_router(privacy_router)
app.include_router(admin_router)
app.include_router(support_router)
app.include_router(observability_router)
app.include_router(integrations_router)
app.include_router(email_webhook_router)
app.include_router(payment_webhook_router)
app.include_router(notifications_router)

from domains.discovery.scheduler import router as discovery_router  # noqa: E402
app.include_router(discovery_router)

# Phase 3 — safeguards / actionable low-barrier surfaces
from domains.credentials.router import router as credentials_router  # noqa: E402
from domains.walkin import router as walkin_router  # noqa: E402
from domains.persona import router as persona_router  # noqa: E402
from domains.dashboard import router as dashboard_router  # noqa: E402
app.include_router(credentials_router)
app.include_router(walkin_router)
app.include_router(persona_router)
app.include_router(dashboard_router)

# Phase 4 — bulk prep, submit sprint, email dry-run, employer intake
from domains.bulk_prep import router as bulk_prep_router  # noqa: E402
from domains.submit_sprint import router as submit_sprint_router  # noqa: E402
from domains.email_route import router as email_route_router  # noqa: E402
from domains.preflight import router as preflight_router  # noqa: E402
from domains.employer_intake import router as employer_intake_router  # noqa: E402
from domains.employer_intake import admin_router as employer_intake_admin_router  # noqa: E402
app.include_router(bulk_prep_router)
app.include_router(submit_sprint_router)
app.include_router(email_route_router)
app.include_router(preflight_router)
app.include_router(employer_intake_router)
app.include_router(employer_intake_admin_router)

# Phase 1 — Conversion Layer (§v Apply Wave, §vii Follow-up drafts)
from domains.wave import router as wave_router  # noqa: E402
from domains.follow_ups import router as follow_ups_router  # noqa: E402
app.include_router(wave_router)
app.include_router(follow_ups_router)
