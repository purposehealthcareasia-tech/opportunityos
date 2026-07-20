from pydantic import BaseModel, Field
from typing import Any, Literal

ClaimType = Literal[
    "identity", "contact", "location", "work_auth", "visa_timeline",
    "education", "employment", "project", "skill", "certification",
    "publication", "reference", "comp_expectation", "availability",
    "preference", "screener_answer", "link",
]

ClaimStatus = Literal["pending", "approved", "rejected", "superseded"]
Sensitivity = Literal["normal", "sealed"]


class CreateClaimRequest(BaseModel):
    type: ClaimType
    value: dict[str, Any]
    sensitivity: Sensitivity = "normal"


class EditClaimRequest(BaseModel):
    value: dict[str, Any]
    sensitivity: Sensitivity | None = None


class BulkApproveRequest(BaseModel):
    type: ClaimType | None = None
    ids: list[str] | None = None
    # Exactly one of {type, ids} should be supplied. Enforced in the service.
