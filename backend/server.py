import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from core.db import ensure_indexes, get_db
from core.policy import CONSENT_SCOPES, policy_version
from middleware.idempotency import IdempotencyMiddleware
from domains.auth.router import router as auth_router
from domains.consent.router import router as consent_router
from domains.users.router import router as users_router
from domains.admin.router import router as admin_router
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
from domains.seeds.seeder import run_seeds

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("oppos")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    log.info("OpportunityOS backend starting…")
    await ensure_indexes()
    try:
        counts = await run_seeds()
        log.info("Seed complete: %s", counts)
    except Exception:
        log.exception("Seeder failed")
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Idempotent-Replay"],
)
app.add_middleware(IdempotencyMiddleware)


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
        "phase": 3,
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
app.include_router(admin_router)
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
