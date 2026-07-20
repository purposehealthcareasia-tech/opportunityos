from fastapi import APIRouter, Header, HTTPException, status
from core.config import settings
from domains.jobs.models import IngestBulkRequest
from domains.jobs import service as jobs_svc

# NOTE ON PATH: Kubernetes ingress requires the /api prefix to route to the backend port.
# So the internal-only bulk-ingest endpoint lives at /api/internal/... instead of /internal/....
# Access is still restricted to holders of INTERNAL_SERVICE_TOKEN — not the user JWT.
router = APIRouter(prefix="/api/internal/jobs", tags=["internal:jobs"])


@router.post("/bulk", status_code=200)
async def bulk_ingest(
    req: IngestBulkRequest,
    x_service_token: str | None = Header(default=None, alias="X-Service-Token"),
):
    expected = settings.INTERNAL_SERVICE_TOKEN
    if not expected:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="internal_service_token_not_configured")
    if not x_service_token or x_service_token != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_service_token")
    return await jobs_svc.ingest_bulk(req, actor="system:ingest")
