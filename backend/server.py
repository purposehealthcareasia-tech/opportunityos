import logging
from collections import Counter
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from core.config import settings
from core.db import ensure_indexes, get_db
from core.policy import CONSENT_SCOPES, policy_version
from core.sessions import ensure_session_indexes
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
from domains.applications.router import router as applications_router
from domains.match_scores.router import router as matches_router
from domains.usage_meters.router import router as usage_router
from domains.screening_answers.router import router as screeners_router
from domains.outcomes.service import router as outcomes_router
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
    log.info("OpportunityOS backend starting…")
    await ensure_indexes()
    await ensure_session_indexes()
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
    yield
    log.info("OpportunityOS backend shutting down…")


app = FastAPI(
    title="OpportunityOS API",
    version="0.1.0",
    openapi_url="/api/openapi.json",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS — explicit allowlist required for credentialed requests (cookies).
# Wildcard "*" + allow_credentials=True is blocked by browsers, so we source
# the origin list from settings.CORS_ALLOW_ORIGINS. Fall back to a permissive
# no-credentials config only when the env var is unset (local dev).
# ---------------------------------------------------------------------------
_origins = [o.strip() for o in (settings.CORS_ALLOW_ORIGINS or "").split(",") if o.strip()]
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


@app.get("/api/health", tags=["meta"])
async def health():
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
        "ci_test_issuer_enabled": bool(settings.CI_TEST_ISSUER_ENABLED),
        "prod_mode": bool(settings.PROD_MODE),
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
app.include_router(applications_router)
app.include_router(matches_router)
app.include_router(usage_router)
app.include_router(screeners_router)
app.include_router(outcomes_router)
app.include_router(subscriptions_router)
app.include_router(inbound_internal_router)
app.include_router(analytics_router)
app.include_router(billing_router)
app.include_router(billing_webhook_router)
app.include_router(privacy_router)
app.include_router(admin_router)
app.include_router(support_router)
app.include_router(observability_router)
