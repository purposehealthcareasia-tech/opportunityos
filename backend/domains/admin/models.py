from pydantic import BaseModel
from typing import Any


class FeatureFlag(BaseModel):
    key: str
    value: Any
    changed_by: str | None = None
