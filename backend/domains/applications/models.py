from pydantic import BaseModel
from typing import Literal

AppState = Literal["shortlisted", "preparing", "awaiting_approval", "approved", "submitting", "submitted", "response", "interview", "offer", "closed"]
Route = Literal["api_native", "extension_assisted", "guided_manual", "email_application", "manual_queue"]


class ApplicationDoc(BaseModel):
    id: str
    user_id: str
    job_id: str
    state: AppState
    route: Route
    route_rationale: str
    materials: dict = {}
    authorization_id: str | None = None
    minutes_to_prepare: int | None = None
    fields_corrected: int | None = None
