"""Public-API adapters for Greenhouse / Lever / Ashby.

Every adapter takes a (company_name, token) and returns a list of
`NormalizedPosting` dicts. Adapters are the ONLY place that speaks HTTP
to the outside world. They must:

  * Only hit the documented public endpoint.
  * Use the shared polite User-Agent.
  * Never construct or invent an `apply_url`. Only pass through what
    the ATS returned.
  * Never touch LinkedIn / Indeed / Handshake.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Iterable, Optional

import httpx


USER_AGENT = "LYNK-Autopilot/preview (contact: privacy@fynd.llc)"
DEFAULT_TIMEOUT = 15.0


# -------------------------------------------------------- new-grad flag
_NEWGRAD_POSITIVE_TITLE = re.compile(
    r"\b("
    r"new\s?grad(uate)?"
    r"|entry\s?level"
    r"|early\s?career"
    r"|junior|jr\.?"
    r"|associate\b"
    r"|university\s+grad"
    r"|university\s+recruiter?"
    r"|university\s+program"
    r"|intern(ship)?\s*(to|-)?\s*(ft|full[-\s]?time|conversion)?"
    r"|apprentice"
    r"|graduate\s+program"
    r"|graduate\s+engineer"
    r"|new\s+college\s+grad(uate)?"
    r"|\bl?i\b|\blvl\s?1\b|\blevel\s?1\b"
    r"|software\s+engineer\s+i\b"
    r")\b",
    re.IGNORECASE,
)
_NEWGRAD_TEXT_NEGATIVE = re.compile(
    r"\b(senior|staff|principal|lead|manager|director|head\s+of|"
    r"vp\b|architect|10\+?\s*years|8\+?\s*years|7\+?\s*years"
    r"|6\+?\s*years|5\+?\s*years)\b",
    re.IGNORECASE,
)
_NEWGRAD_TEXT_POSITIVE = re.compile(
    r"\b("
    r"(0|zero)\s*(-|to)\s*2\s*years"
    r"|0\+\s*years"
    r"|no\s+prior\s+experience"
    r"|no\s+experience\s+required"
    r"|new\s+grad"
    r"|recent\s+(college\s+)?grad(uate)?"
    r"|early\s+in\s+your\s+career"
    r"|will\s+train"
    r"|university\s+recruit"
    r")\b",
    re.IGNORECASE,
)


def detect_newgrad(title: str, description_text: str) -> bool:
    """Return True iff the posting's title/description contain
    supportive language for a new-grad / entry-level / 0-2y role AND
    do not contain unambiguous seniority contradictions.

    Never fabricates: if the text is silent, returns False."""
    if not title:
        return False
    title_hit = bool(_NEWGRAD_POSITIVE_TITLE.search(title))
    body_hit = bool(_NEWGRAD_TEXT_POSITIVE.search(description_text or ""))
    negative = bool(_NEWGRAD_TEXT_NEGATIVE.search(f"{title} {description_text or ''}"))
    if negative and not (title_hit or body_hit):
        return False
    return bool(title_hit or body_hit)


# -------------------------------------------------------- shared helpers
def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=DEFAULT_TIMEOUT,
        follow_redirects=True,
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt_or_str) -> Optional[str]:
    if dt_or_str is None:
        return None
    if isinstance(dt_or_str, datetime):
        return dt_or_str.astimezone(timezone.utc).isoformat()
    try:
        return str(dt_or_str)
    except Exception:
        return None


def _strip_html(html: str, max_len: int = 6000) -> str:
    if not html:
        return ""
    txt = re.sub(r"<[^>]+>", " ", html)
    txt = re.sub(r"&nbsp;|&#160;", " ", txt)
    txt = re.sub(r"&amp;", "&", txt)
    txt = re.sub(r"&lt;", "<", txt)
    txt = re.sub(r"&gt;", ">", txt)
    txt = re.sub(r"&quot;", '"', txt)
    txt = re.sub(r"&#39;|&apos;", "'", txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt[:max_len]


# -------------------------------------------------------- adapters
async def fetch_greenhouse(company_name: str, token: str) -> list[dict]:
    """Public Greenhouse Job Board API — unauthenticated JSON.
    Docs: https://developers.greenhouse.io/job-board.html
    """
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
    async with _client() as c:
        r = await c.get(url)
    if r.status_code != 200:
        return []
    data = r.json()
    out = []
    for j in data.get("jobs", []):
        apply_url = j.get("absolute_url")
        if not apply_url:
            continue
        title = (j.get("title") or "").strip()
        loc_name = (j.get("location") or {}).get("name") or ""
        jd = _strip_html(j.get("content") or "")
        posted = j.get("first_published") or j.get("updated_at")
        updated = j.get("updated_at")
        departments = ", ".join(d.get("name", "") for d in (j.get("departments") or []) if d)
        out.append({
            "source_ats": "greenhouse",
            "employer": company_name,
            "employer_token": token,
            "external_id": str(j.get("id") or j.get("internal_job_id") or ""),
            "requisition_reference": (j.get("requisition_id") or None),
            "title": title,
            "location": loc_name,
            "remote": _guess_remote(loc_name, j.get("content") or ""),
            "posted_at": _iso(posted),
            "updated_at": _iso(updated),
            "apply_url": apply_url,
            "jd_text": jd,
            "department": departments or None,
            "employment_type": None,
            "is_newgrad": detect_newgrad(title, jd),
            "fetched_at": _iso(_now()),
        })
    return out


async def fetch_lever(company_name: str, token: str) -> list[dict]:
    """Public Lever Postings API — unauthenticated JSON.
    Docs: https://github.com/lever/postings-api
    """
    for host in ("api.lever.co", "api.eu.lever.co"):
        url = f"https://{host}/v0/postings/{token}?mode=json"
        try:
            async with _client() as c:
                r = await c.get(url)
        except Exception:
            continue
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list) and data:
                return _lever_normalize(company_name, token, data, host)
    return []


def _lever_normalize(company_name: str, token: str, data: list, host: str) -> list[dict]:
    out = []
    for j in data:
        apply_url = j.get("applyUrl") or j.get("hostedUrl")
        if not apply_url:
            continue
        title = (j.get("text") or "").strip()
        cats = j.get("categories") or {}
        loc = cats.get("location") or ""
        team = cats.get("team") or ""
        commit = cats.get("commitment") or ""
        posted_ms = j.get("createdAt")
        posted_iso = None
        if isinstance(posted_ms, (int, float)) and posted_ms > 0:
            posted_iso = datetime.fromtimestamp(posted_ms / 1000, tz=timezone.utc).isoformat()
        jd = _strip_html((j.get("descriptionBody") or "") + " " + (j.get("additionalPlain") or ""))
        workplace = (j.get("workplaceType") or "").lower()
        remote = workplace == "remote" or "remote" in loc.lower()
        out.append({
            "source_ats": "lever",
            "employer": company_name,
            "employer_token": token,
            "external_id": str(j.get("id") or ""),
            "requisition_reference": None,
            "title": title,
            "location": loc,
            "remote": remote,
            "posted_at": posted_iso,
            "updated_at": posted_iso,
            "apply_url": apply_url,
            "jd_text": jd,
            "department": team or None,
            "employment_type": commit or None,
            "is_newgrad": detect_newgrad(title, jd),
            "fetched_at": _iso(_now()),
        })
    return out


async def fetch_ashby(company_name: str, token: str) -> list[dict]:
    """Public Ashby Job-Posting API — unauthenticated JSON.
    Docs: https://developers.ashbyhq.com/docs/public-job-posting-api
    """
    url = f"https://api.ashbyhq.com/posting-api/job-board/{token}"
    async with _client() as c:
        r = await c.get(url)
    if r.status_code != 200:
        return []
    data = r.json()
    out = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        apply_url = j.get("applyUrl") or j.get("jobUrl")
        if not apply_url:
            continue
        title = (j.get("title") or "").strip()
        loc = (j.get("location") or "").strip()
        jd = _strip_html(j.get("descriptionPlain") or j.get("descriptionHtml") or "")
        remote = bool(j.get("isRemote")) or (j.get("workplaceType") or "").lower() == "remote"
        out.append({
            "source_ats": "ashby",
            "employer": company_name,
            "employer_token": token,
            "external_id": str(j.get("id") or ""),
            "requisition_reference": None,
            "title": title,
            "location": loc,
            "remote": remote,
            "posted_at": _iso(j.get("publishedAt")),
            "updated_at": _iso(j.get("publishedAt")),
            "apply_url": apply_url,
            "jd_text": jd,
            "department": j.get("department") or None,
            "employment_type": j.get("employmentType") or None,
            "is_newgrad": detect_newgrad(title, jd),
            "fetched_at": _iso(_now()),
        })
    return out


def _guess_remote(location: str, content: str) -> bool:
    loc = (location or "").lower()
    if "remote" in loc:
        return True
    # Very conservative: don't infer remote from body unless location is silent.
    if not loc and re.search(r"\bfully\s+remote\b|\b100%\s+remote\b", (content or ""), re.IGNORECASE):
        return True
    return False


FETCHERS = {
    "greenhouse": fetch_greenhouse,
    "lever":      fetch_lever,
    "ashby":      fetch_ashby,
}
