from pydantic import BaseModel, Field
from datetime import datetime
from typing import Any


class DocumentDoc(BaseModel):
    id: str
    user_id: str
    kind: str  # "resume" for now
    original_filename: str
    content_type: str
    size_bytes: int
    s3_key: str
    sha256: str
    av_status: str = "skipped_v0.1"  # honestly labeled — no AV in Phase 2
    parse_status: str = "queued"  # queued | extracting | parsing | completed | failed
    parse_error: str | None = None
    parse_meta: dict[str, Any] = Field(default_factory=dict)  # {model_used, claim_count, ...}
    created_at: datetime
    updated_at: datetime


class DocumentResponse(BaseModel):
    id: str
    kind: str
    original_filename: str
    content_type: str
    size_bytes: int
    sha256: str
    av_status: str
    parse_status: str
    parse_error: str | None = None
    parse_meta: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
