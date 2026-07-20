from fastapi import APIRouter, Depends, Header, HTTPException, status
from core.config import settings
from domains.jobs.models import IngestBulkRequest
from domains.jobs import service as jobs_svc

# NOTE ON PATH: Kubernetes ingress requires the /api prefix to route to the backend port.
# So the internal-only bulk-ingest endpoint lives at /api/internal/... instead of /internal/....
# Access is still restricted to holders of INTERNAL_SERVICE_TOKEN — not the user JWT.
router = APIRouter(prefix="/api/internal/jobs", tags=["internal:jobs"])


async def _check_service_token(
    x_service_token: str | None = Header(default=None, alias="X-Service-Token"),
):
    """Depends(): validates the internal service token BEFORE FastAPI runs body validation.

    Founder Directive #1 semantics:
      - 503 ONLY when the server has no INTERNAL_SERVICE_TOKEN configured.
      - 401 when the header is missing.
      - 403 when the header is present but wrong.
      - Token value is NEVER logged / returned / included in error bodies.
    """
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


@router.post("/bulk", status_code=200, dependencies=[Depends(_check_service_token)])
async def bulk_ingest(req: IngestBulkRequest):
    return await jobs_svc.ingest_bulk(req, actor="system:ingest")
