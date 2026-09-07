"""USAJOBS Search API adapter — CONFIG-REQUIRED.

Docs (verified against https://developer.usajobs.gov current guidance):
* Endpoint:  https://data.usajobs.gov/api/search
* Method:    GET (query params)
* Required headers:
    Host:               data.usajobs.gov
    User-Agent:         <the email you registered with USAJOBS>
    Authorization-Key:  <the API key issued to that email>

Both values MUST be provided by the founder. Registration is free at
https://developer.usajobs.gov (create-a-key page). This adapter refuses
to run until BOTH env vars are set:

    USAJOBS_USER_AGENT_EMAIL   # e.g. "privacy@fynd.llc"
    USAJOBS_API_KEY            # the key USAJOBS emails you

Rails:
* No fabrication of an identity — this adapter deliberately does NOT
  hard-code a fake email or reuse a preview password. Without a real
  founder-owned email + issued key, the adapter no-ops and reports
  CONFIG-REQUIRED in the audit trail.
* Returns rows in the same normalized shape as the Greenhouse/Lever/
  Ashby adapters so `service.py` can upsert without special-casing.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Optional

import httpx


BASE_URL = "https://data.usajobs.gov/api/search"


def _is_configured() -> bool:
    return bool(os.environ.get("USAJOBS_API_KEY")
                and os.environ.get("USAJOBS_USER_AGENT_EMAIL"))


def status_reason() -> str:
    if _is_configured():
        return "ready"
    missing = []
    if not os.environ.get("USAJOBS_API_KEY"):
        missing.append("USAJOBS_API_KEY")
    if not os.environ.get("USAJOBS_USER_AGENT_EMAIL"):
        missing.append("USAJOBS_USER_AGENT_EMAIL")
    return f"config_required:missing={','.join(missing)}"


async def fetch_usajobs(location_name: Optional[str] = "Phoenix, Arizona",
                        results_per_page: int = 250,
                        max_pages: int = 8) -> list[dict]:
    """Fetch federal postings via USAJOBS Search API.
    Returns a list of normalized posting dicts (same shape as the
    other adapters). Returns an empty list + logs CONFIG-REQUIRED if
    creds are not present.

    P1 Batch 2 · gate: FETCH must be permitted by source_policy for
    `usajobs` before the HTTP client is constructed. Fail-CLOSED.
    """
    if not _is_configured():
        return []

    # Deferred import — same rationale as public_apis._gate (avoid
    # circular import chain at module load time).
    from domains.source_policy import Operation, PolicyDenied, PolicyDecision, allow
    from domains.source_registry import get as _reg_get
    from core.time_utils import utc_now
    _rec = await _reg_get("usajobs")
    if _rec is None:
        raise PolicyDenied(PolicyDecision(
            allowed=False, reason="source_not_in_registry",
            source_id="usajobs", operation=Operation.FETCH.value,
            evaluated_at=utc_now().isoformat(), field_values={},
        ))
    allow(source_record=_rec, operation=Operation.FETCH).raise_if_denied()

    ua_email = os.environ["USAJOBS_USER_AGENT_EMAIL"]
    key = os.environ["USAJOBS_API_KEY"]

    headers = {
        "Host": "data.usajobs.gov",
        "User-Agent": ua_email,
        "Authorization-Key": key,
        "Accept": "application/json",
    }

    out: list[dict] = []
    async with httpx.AsyncClient(headers=headers, timeout=20.0) as c:
        for page in range(1, max_pages + 1):
            params = {
                "LocationName": location_name or "",
                "ResultsPerPage": results_per_page,
                "Page": page,
                "SortField": "OpenDate",
                "SortDirection": "Desc",
            }
            r = await c.get(BASE_URL, params=params)
            if r.status_code != 200:
                break
            try:
                data = r.json()
            except Exception:
                break
            items = ((data.get("SearchResult") or {})
                     .get("SearchResultItems") or [])
            if not items:
                break
            for it in items:
                md = it.get("MatchedObjectDescriptor") or {}
                if not md:
                    continue
                external_id = str(md.get("PositionID") or md.get("MatchedObjectId") or "")
                apply_url = md.get("ApplyURI")
                if isinstance(apply_url, list) and apply_url:
                    apply_url = apply_url[0]
                if not apply_url:
                    apply_url = md.get("PositionURI")
                if not (external_id and apply_url):
                    continue
                title = md.get("PositionTitle") or ""
                org = md.get("OrganizationName") or "US Federal Government"
                locations = md.get("PositionLocationDisplay") or ""
                start_date = md.get("PublicationStartDate")
                end_date = md.get("PublicationEndDate")
                # Employment / hiring path
                path_display = ", ".join(md.get("HiringPath") or [])
                employment_type = None
                schedule = md.get("PositionSchedule") or []
                if schedule:
                    employment_type = (schedule[0] or {}).get("Name")
                # JD text: bring in Duties + summary if present
                jd = ""
                udesc = (md.get("UserArea") or {}).get("Details") or {}
                if udesc:
                    jd = _strip_html(
                        " ".join([udesc.get("MajorDuties","")
                                   if isinstance(udesc.get("MajorDuties"), str)
                                   else " ".join(udesc.get("MajorDuties") or []),
                                  udesc.get("JobSummary") or ""])
                    )
                out.append({
                    "source_ats": "usajobs",
                    "employer": org,
                    "employer_token": "usajobs-federal",
                    "external_id": external_id,
                    "requisition_reference": md.get("PositionID"),
                    "title": title,
                    "location": locations,
                    "remote": "remote" in (locations or "").lower(),
                    "posted_at": start_date,
                    "updated_at": end_date,
                    "apply_url": apply_url,
                    "jd_text": jd[:6000],
                    "department": path_display or None,
                    "employment_type": employment_type,
                    "is_newgrad": False,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "hiring_path": path_display or None,
                })
            # If fewer than requested, we're done.
            if len(items) < results_per_page:
                break
    return out


def _strip_html(html: str) -> str:
    if not html:
        return ""
    txt = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", txt).strip()
