from pydantic import BaseModel, Field, field_validator
from typing import Any, Literal

JobStatus = Literal["live", "stale", "expired", "blocked", "derived"]


class EligibilityRequirements(BaseModel):
    requires_us_person: bool = False
    offers_sponsorship: bool | None = None
    accepted_statuses: list[str] | None = None
    requires_security_clearance: bool = False
    notes: str | None = None


class JobRequirements(BaseModel):
    skills_required: list[str] = Field(default_factory=list)
    degree_level: str | None = None
    years_min: int | None = None
    licenses: list[str] = Field(default_factory=list)


class IngestJob(BaseModel):
    canonical_key: str = Field(min_length=3, max_length=300)
    origin_url: str = Field(min_length=1, max_length=1000)
    title: str = Field(min_length=1, max_length=300)
    company_name: str = Field(min_length=1, max_length=200)
    company_domain: str | None = Field(default=None, max_length=200)
    source: str = Field(default="ingest", max_length=64)
    taxonomy_family: str | None = None
    geo: str | None = None
    comp: str | None = None
    jd_text: str = Field(min_length=10, max_length=50_000)
    apply_method: str = Field(default="external", max_length=64)
    eligibility_requirements: EligibilityRequirements | None = None
    requirements: JobRequirements | None = None
    is_sample: bool = False

    @field_validator("canonical_key")
    @classmethod
    def _key(cls, v: str) -> str:
        if "::" not in v:
            raise ValueError("canonical_key must include a '::' separator, e.g. 'employer_domain::job_id'.")
        return v.strip()


class IngestBulkRequest(BaseModel):
    jobs: list[IngestJob] = Field(min_length=1, max_length=1000)


class ImportRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2000)
    title: str | None = Field(default=None, max_length=300)
    company_name: str | None = Field(default=None, max_length=200)


class ResolveOriginRequest(BaseModel):
    origin_url: str = Field(min_length=8, max_length=2000)
    notes: str | None = Field(default=None, max_length=1000)


class HideRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=200)  # e.g. "not_interested", "location", "comp"
