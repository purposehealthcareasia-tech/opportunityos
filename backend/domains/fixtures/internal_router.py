"""Internal fixture-rebase endpoint (Founder Fix Round 2 · P0 #1).

Gate: same INTERNAL_SERVICE_TOKEN semantics as `/api/internal/jobs/bulk`
(missing→401, wrong→403, not-configured→503; token never logged / returned).

The fixture user auto-rebases on backend startup, but persistent test runs mutate state
between restarts. Testers call this endpoint BEFORE each acceptance run to guarantee the
9/6 geometry is reachable without restarting supervisor.

Only affects `fixture-ead@opportunityos.dev`. Real users (User Zero, admin, support) are
never touched by this path.
"""
from fastapi import APIRouter, Depends, Header, HTTPException, status
from core.config import settings
from domains.seeds import seeder

router = APIRouter(prefix="/api/internal/fixture", tags=["internal:fixture"])


async def _check_service_token(
    x_service_token: str | None = Header(default=None, alias="X-Service-Token"),
):
    expected = settings.INTERNAL_SERVICE_TOKEN
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "internal_service_token_not_configured"},
        )
    if not x_service_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "service_token_missing"},
        )
    if x_service_token != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "service_token_invalid"},
        )
    return True


@router.post("/rebase", status_code=200, dependencies=[Depends(_check_service_token)])
async def rebase_fixture():
    """Nuke all mutable state for the fixture user and re-seed to acceptance-check-B."""
    fx_id = await seeder._rebase_fixture_user()
    return {
        "ok": True,
        "fixture_user_id": fx_id,
        "note": "fixture-ead@opportunityos.dev re-baselined. Applications, hidden_jobs, "
                "match_scores, usage_meters, documents, resume_versions, score_feedback, "
                "claims, consent_records were wiped. All acceptance state re-seeded.",
    }
