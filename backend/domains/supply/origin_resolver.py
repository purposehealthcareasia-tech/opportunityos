"""Phase 3 · Origin resolver — cross-references a submitted URL against
the same discovery-provider taxonomy Fynd's 157 verified boards use.

Contract
--------
`resolve(url_or_host)` returns:
    {
      "provider": "greenhouse" | "lever" | "ashby" | "workday" | None,
      "token":    str | None,           # provider-scoped board token
      "canonical_host": str,             # www-stripped, lowercased host
      "verdict":  "verifiable_board" | "unrecognized_host",
      "note":     str,                   # plain-language why
    }

`verifiable_board` means the URL matches one of the well-known board
patterns (Greenhouse boards / Lever hosted careers / Ashby hosted
careers / Workday tenant); the extracted token is a real board handle
that a future admin triage step can point the catalog at.

`unrecognized_host` means we can't semantically place this URL — it may
still be a legitimate careers page (Notion doc, careers site of a
company that manages its own ATS), so we KEEP the submission with
`status="unrecognized_host"` for founder triage. We do NOT reject it —
that would silently drop legitimate long-tail submissions.

This module is pattern-only (no network). Live probes remain the
admin-triage step (same code path the 157 use in `discovery/catalog.py`
via `catalog_expand.py`), invoked out-of-band.
"""
from __future__ import annotations
import re
from urllib.parse import urlparse


# Patterns pulled from discovery/adapters/public_apis.py, matched
# against real board URLs.
_GREENHOUSE_HOST_RE = re.compile(r"^boards\.greenhouse\.io$", re.I)
_GREENHOUSE_TOKEN_PATH_RE = re.compile(r"^/(?:embed/job_board\?for=)?([a-z0-9_-]+)", re.I)

_LEVER_HOST_RE = re.compile(r"^jobs\.lever\.co$", re.I)
_LEVER_TOKEN_PATH_RE = re.compile(r"^/([a-z0-9_-]+)", re.I)

_ASHBY_HOST_RE = re.compile(r"^jobs\.ashbyhq\.com$", re.I)
_ASHBY_TOKEN_PATH_RE = re.compile(r"^/([a-z0-9_.-]+)", re.I)

# Workday tenants: `<tenant>.wd<n>.myworkdayjobs.com`
_WORKDAY_HOST_RE = re.compile(
    r"^(?P<tenant>[a-z0-9-]+)\.wd\d+\.myworkdayjobs\.com$", re.I,
)


def resolve(url: str) -> dict:
    """Pure-pattern resolver. Never hits the network."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    canonical = host or ""
    path = parsed.path or "/"

    # 1) Greenhouse: boards.greenhouse.io/<token>
    if _GREENHOUSE_HOST_RE.match(host):
        m = _GREENHOUSE_TOKEN_PATH_RE.match(path)
        if m:
            return {
                "provider": "greenhouse",
                "token": m.group(1),
                "canonical_host": canonical,
                "verdict": "verifiable_board",
                "note": (f"Greenhouse board detected. Token `{m.group(1)}` "
                          "can be verified via boards-api.greenhouse.io "
                          "at admin-triage time."),
            }

    # 2) Lever: jobs.lever.co/<token>
    if _LEVER_HOST_RE.match(host):
        m = _LEVER_TOKEN_PATH_RE.match(path)
        if m:
            return {
                "provider": "lever",
                "token": m.group(1),
                "canonical_host": canonical,
                "verdict": "verifiable_board",
                "note": (f"Lever board detected. Token `{m.group(1)}` can "
                          "be verified via api.lever.co/v0/postings at "
                          "admin-triage time."),
            }

    # 3) Ashby: jobs.ashbyhq.com/<token>
    if _ASHBY_HOST_RE.match(host):
        m = _ASHBY_TOKEN_PATH_RE.match(path)
        if m:
            return {
                "provider": "ashby",
                "token": m.group(1),
                "canonical_host": canonical,
                "verdict": "verifiable_board",
                "note": (f"Ashby board detected. Token `{m.group(1)}` "
                          "can be verified via api.ashbyhq.com/"
                          "posting-api/job-board at admin-triage time."),
            }

    # 4) Workday: <tenant>.wd<n>.myworkdayjobs.com
    m = _WORKDAY_HOST_RE.match(host)
    if m:
        return {
            "provider": "workday",
            "token": m.group("tenant"),
            "canonical_host": canonical,
            "verdict": "verifiable_board",
            "note": (f"Workday tenant `{m.group('tenant')}` detected. See "
                      "docs/WORKDAY-SPEC.md for the not-yet-shipped "
                      "adapter path."),
        }

    # 5) Unrecognized — keep for founder triage; NEVER silent-reject.
    return {
        "provider": None,
        "token": None,
        "canonical_host": canonical,
        "verdict": "unrecognized_host",
        "note": ("Host doesn't match any known board pattern "
                 "(Greenhouse / Lever / Ashby / Workday). Kept for "
                 "founder triage — may still be a legitimate long-tail "
                 "careers surface."),
    }
