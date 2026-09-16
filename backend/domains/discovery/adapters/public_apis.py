"""Public-API adapters for Greenhouse / Lever / Ashby.

Every adapter takes a (company_name, token) and returns a list of
`NormalizedPosting` dicts. Adapters are the ONLY place that speaks HTTP
to the outside world. They must:

  * Only hit the documented public endpoint.
  * Use the shared polite User-Agent.
  * Never construct or invent an `apply_url`. Only pass through what
    the ATS returned.
  * Never touch LinkedIn / Indeed / Handshake.

P1 FOUNDATION Batch 2 · policy gate. Every module-level fetch function
below routes its (source_id, Operation.FETCH) tuple through
`source_policy.allow(...)` BEFORE constructing the HTTP client. This
makes fail-CLOSED an invariant of the network op site itself — the
gate runs whether the caller uses the SDK connector classes at the
bottom of this file OR calls the module-level functions directly.
`_gate` is async so it can read the (small) `source_registry` record
via motor without blocking the loop.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Iterable, Optional

from domains.source_policy import Operation
from domains.discovery.connector_sdk import OpportunitySourceConnector
from domains.discovery.adapters.http import policy_gated_client, DEFAULT_USER_AGENT

# Kept for byte-identical public surface — tests and callers may still
# import USER_AGENT / DEFAULT_TIMEOUT from public_apis.
USER_AGENT = DEFAULT_USER_AGENT
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
# Client construction routed through the guarded factory
# `domains/discovery/adapters/http.py::policy_gated_client`. The gate
# runs once, at construction time; the yielded httpx.AsyncClient is
# byte-identical to the pre-hardening client.


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

    P1 Batch 2 · gate: FETCH must be permitted by source_policy for
    `greenhouse` before the HTTP client is constructed. Fail-CLOSED —
    no network op fires on DENY. Batch 5 hardening: gate now enforced
    inside `policy_gated_client(...)`, not a per-adapter call.
    """
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
    async with policy_gated_client("greenhouse", Operation.FETCH) as c:
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

    P1 Batch 2 · gate: FETCH must be permitted by source_policy for
    `lever` before the HTTP client is constructed. Fail-CLOSED.
    Batch 5 hardening: gate enforced inside `policy_gated_client(...)`.
    """
    for host in ("api.lever.co", "api.eu.lever.co"):
        url = f"https://{host}/v0/postings/{token}?mode=json"
        try:
            async with policy_gated_client("lever", Operation.FETCH) as c:
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

    P1 Batch 2 · gate: FETCH must be permitted by source_policy for
    `ashby` before the HTTP client is constructed. Fail-CLOSED.
    Batch 5 hardening: gate enforced inside `policy_gated_client(...)`.
    """
    url = f"https://api.ashbyhq.com/posting-api/job-board/{token}"
    async with policy_gated_client("ashby", Operation.FETCH) as c:
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
        # P1 Batch 3 · country_allowlist. Ashby exposes structured
        # `address.postalAddress.addressCountry` on the primary location
        # AND on each `secondaryLocations[].address.postalAddress`.
        # Populate ONLY from those fields; never inferred from free-text.
        countries = _ashby_countries(j)
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
            "country_allowlist": countries,
        })
    return out


# ------------------------------------------------ Country normalization
# Ashby returns full country names ("United States", "Japan", "United Kingdom").
# USAJOBS returns full names too. Map to ISO-3166-1 alpha-2 so the downstream
# gate engine can compare against user.location.country deterministically.
# The mapping is deliberately conservative — unknown country names return
# None (the row's country_allowlist stays [] not populated). Never fuzzy.
_ASHBY_COUNTRY_ISO2: dict[str, str] = {
    "united states":  "US", "usa": "US", "u.s.": "US", "u.s.a.": "US",
    "canada":         "CA",
    "united kingdom": "GB", "uk": "GB", "great britain": "GB",
    "germany":        "DE",
    "france":         "FR",
    "spain":          "ES",
    "italy":          "IT",
    "netherlands":    "NL",
    "belgium":        "BE",
    "switzerland":    "CH",
    "austria":        "AT",
    "ireland":        "IE",
    "sweden":         "SE",
    "norway":         "NO",
    "denmark":        "DK",
    "finland":        "FI",
    "poland":         "PL",
    "portugal":       "PT",
    "japan":          "JP",
    "china":          "CN",
    "india":          "IN",
    "singapore":      "SG",
    "australia":      "AU",
    "new zealand":    "NZ",
    "mexico":         "MX",
    "brazil":         "BR",
    "argentina":      "AR",
    "chile":          "CL",
    "colombia":       "CO",
    "israel":         "IL",
    "united arab emirates": "AE", "uae": "AE",
    "south africa":   "ZA",
    "south korea":    "KR", "korea, republic of": "KR",
    "hong kong":      "HK",
    "taiwan":         "TW",
    "philippines":    "PH",
    "indonesia":      "ID",
    "malaysia":       "MY",
    "thailand":       "TH",
    "vietnam":        "VN",
    "turkey":         "TR",
    "estonia":        "EE",
    "czech republic": "CZ", "czechia": "CZ",
    "romania":        "RO",
    "greece":         "GR",
    "hungary":        "HU",
}


def _to_iso2(country_name: str | None) -> str | None:
    if not country_name:
        return None
    key = country_name.strip().lower()
    return _ASHBY_COUNTRY_ISO2.get(key)


def _ashby_countries(job: dict) -> list[str] | None:
    """Extract ISO-3166-1 alpha-2 codes from Ashby's structured address
    fields. Returns:
      * a non-empty sorted list of unique codes when at least one
        addressCountry could be mapped; OR
      * None when the row has no structured country data at all (so
        the `indeterminate` bucket stays honest).
    Unknown names in the mapping table produce None (never inferred).
    """
    hits: set[str] = set()
    prim = ((job.get("address") or {}).get("postalAddress") or {}).get("addressCountry")
    code = _to_iso2(prim)
    if code:
        hits.add(code)
    for sec in (job.get("secondaryLocations") or []):
        sec_country = ((sec.get("address") or {}).get("postalAddress") or {}).get("addressCountry")
        c = _to_iso2(sec_country)
        if c:
            hits.add(c)
    return sorted(hits) if hits else None


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


# ============================================================================
# P1 FOUNDATION Batch 2 · SDK connector classes
#
# Thin wrappers over the module-level fetchers. Each class exposes the
# `OpportunitySourceConnector` interface so the eventual scheduler (and
# admin ops surfaces) can consume every source through a single contract.
# Byte-identical output rail: the connector's `fetch(name, token)` returns
# EXACTLY what `fetch_<source>(name, token)` returns for the same inputs.
# The policy gate runs inside the module-level fetcher (single choke-
# point), so calling the connector or the raw function produces the same
# fail-CLOSED behaviour.
# ============================================================================
class GreenhouseConnector(OpportunitySourceConnector):
    source_id = "greenhouse"

    async def discover(self) -> list[tuple[str, str]]:
        await self.check_policy(Operation.DISCOVER)
        from domains.discovery.catalog import ALL_BOARDS
        return [(name, token) for (ats, name, token) in ALL_BOARDS
                if ats == self.source_id]

    async def fetch(self, company_name: str, token: str) -> list[dict]:
        # Module-level fetcher enforces the policy gate at the network
        # op site — no double gate, byte-identical output vs. calling
        # `fetch_greenhouse(...)` directly.
        return await fetch_greenhouse(company_name, token)


class LeverConnector(OpportunitySourceConnector):
    source_id = "lever"

    async def discover(self) -> list[tuple[str, str]]:
        await self.check_policy(Operation.DISCOVER)
        from domains.discovery.catalog import ALL_BOARDS
        return [(name, token) for (ats, name, token) in ALL_BOARDS
                if ats == self.source_id]

    async def fetch(self, company_name: str, token: str) -> list[dict]:
        return await fetch_lever(company_name, token)


class AshbyConnector(OpportunitySourceConnector):
    source_id = "ashby"

    async def discover(self) -> list[tuple[str, str]]:
        await self.check_policy(Operation.DISCOVER)
        from domains.discovery.catalog import ALL_BOARDS
        return [(name, token) for (ats, name, token) in ALL_BOARDS
                if ats == self.source_id]

    async def fetch(self, company_name: str, token: str) -> list[dict]:
        return await fetch_ashby(company_name, token)


CONNECTORS: dict[str, type[OpportunitySourceConnector]] = {
    "greenhouse": GreenhouseConnector,
    "lever":      LeverConnector,
    "ashby":      AshbyConnector,
}
