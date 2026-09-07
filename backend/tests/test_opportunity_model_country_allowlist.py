"""P1 FOUNDATION Batch 3 · Canonical Opportunity Model + country_allowlist.

Locks:
  * `EligibilityRequirements` accepts `country_allowlist: list[str] | None`.
  * `country_allowlist` is populated ONLY from real source fields
    (Ashby address.postalAddress.addressCountry; USAJOBS federal ⇒ US).
    GH/Lever adapters MUST leave it None (never inferred).
  * Free-text location must NOT populate country_allowlist — an Ashby
    row without a structured address returns None even if the free-text
    location contains a country name.
  * The `/standards` per-country coverage shrinks the `indeterminate`
    bucket by exactly the number of country_allowlist-classified remote
    rows. SAMPLE/fixture exclusion invariant is preserved.
"""
from __future__ import annotations

import pytest
import pytest_asyncio


@pytest_asyncio.fixture(autouse=True)
async def _reset_motor_and_registry():
    from core import db as _core_db
    _core_db._client = None
    _core_db._db = None
    db = _core_db.get_db()
    await db.source_registry.delete_many({})
    yield


# ---------------------------------------------------------------- schema
def test_eligibility_requirements_accepts_country_allowlist():
    from domains.jobs.models import EligibilityRequirements
    # None is the default (indeterminate).
    e0 = EligibilityRequirements()
    assert e0.country_allowlist is None
    # ISO-3166 alpha-2 codes are accepted.
    e1 = EligibilityRequirements(country_allowlist=["US"])
    assert e1.country_allowlist == ["US"]
    e2 = EligibilityRequirements(country_allowlist=["US", "CA", "GB"])
    assert e2.country_allowlist == ["US", "CA", "GB"]


# ---------------------------------------------------------------- ashby extraction
def test_ashby_extracts_country_from_structured_address():
    """Real Ashby response payload — primary + secondary address country."""
    from domains.discovery.adapters.public_apis import _ashby_countries
    job = {
        "location": "San Francisco, California",
        "address": {"postalAddress": {"addressCountry": "United States"}},
        "secondaryLocations": [
            {"address": {"postalAddress": {"addressCountry": "United States"}}},
            {"address": {"postalAddress": {"addressCountry": "Canada"}}},
        ],
    }
    assert _ashby_countries(job) == ["CA", "US"]


def test_ashby_returns_none_when_no_structured_address():
    """Free-text location without any address.postalAddress → None.
    Rail: never inferred from free-text."""
    from domains.discovery.adapters.public_apis import _ashby_countries
    job1 = {"location": "United States", "address": None,
            "secondaryLocations": None}
    assert _ashby_countries(job1) is None
    job2 = {"location": "Anywhere on Earth",
            "address": {"postalAddress": {}},  # empty postalAddress
            "secondaryLocations": []}
    assert _ashby_countries(job2) is None


def test_ashby_unknown_country_name_returns_none_never_fuzzy():
    """Country names not in the deterministic mapping table map to
    None — never fuzzy-matched. Preserves the 'never fabricate' rail."""
    from domains.discovery.adapters.public_apis import _ashby_countries
    job = {"address": {"postalAddress": {"addressCountry": "Wakanda"}},
           "secondaryLocations": []}
    assert _ashby_countries(job) is None


def test_ashby_iso2_mapping_normalizes_common_variants():
    """USA / U.S. / United States all map to 'US' — deterministic
    normalization only, no fuzzy matching."""
    from domains.discovery.adapters.public_apis import _to_iso2
    assert _to_iso2("United States") == "US"
    assert _to_iso2("usa") == "US"
    assert _to_iso2("U.S.") == "US"
    assert _to_iso2("United Kingdom") == "GB"
    assert _to_iso2("UK") == "GB"
    # Trailing whitespace and case-insensitive.
    assert _to_iso2("  Japan  ") == "JP"
    # Empty/None → None.
    assert _to_iso2("") is None
    assert _to_iso2(None) is None


# ---------------------------------------------------------------- gh / lever leave None
@pytest.mark.asyncio
async def test_greenhouse_output_does_not_emit_country_allowlist():
    """GH adapter does not have structured country data in its response
    schema — the emitted normalized row MUST NOT carry a
    country_allowlist key (or emit None). Rail: never inferred."""
    import httpx
    from domains.source_registry import seed_verified_sources
    from domains.discovery.adapters import public_apis
    from domains.discovery.adapters.public_apis import fetch_greenhouse
    await seed_verified_sources()

    canned = {"jobs": [{
        "id": 1, "title": "SWE", "location": {"name": "Remote (US)"},
        "content": "<p>desc</p>", "first_published": "2026-02-15",
        "updated_at": "2026-02-15", "absolute_url": "https://boards.greenhouse.io/x/jobs/1",
        "departments": [],
    }]}

    def _handler(req): return httpx.Response(200, json=canned)
    transport = httpx.MockTransport(_handler)

    async def _mock_client_ctx():
        return httpx.AsyncClient(transport=transport,
                                 headers={"User-Agent": public_apis.USER_AGENT,
                                          "Accept": "application/json"})
    # Monkeypatch _client to yield an async context manager compatible client.
    original_client = public_apis._client
    public_apis._client = lambda: httpx.AsyncClient(
        transport=transport,
        headers={"User-Agent": public_apis.USER_AGENT,
                 "Accept": "application/json"},
    )
    try:
        rows = await fetch_greenhouse("Acme", "acme")
    finally:
        public_apis._client = original_client

    assert len(rows) == 1
    # Rail: GH row must not carry a country_allowlist (either absent
    # or None). Never fabricated from free-text.
    assert rows[0].get("country_allowlist") in (None, [])


# ---------------------------------------------------------------- standards coverage
@pytest.mark.asyncio
async def test_standards_country_coverage_uses_allowlist_shrinks_indeterminate():
    """Insert 5 remote jobs:
       * 2 with country_allowlist=['US']
       * 1 with country_allowlist=['IN','US']
       * 2 with country_allowlist=None (indeterminate free-text)
    Expect: indeterminate=2, us_only=2, india_explicit=1,
    country_allowlist_classified=3.
    Rail: SAMPLE row is excluded even when it carries an allowlist."""
    from core.db import get_db
    from domains.standards import metrics
    db = get_db()
    await db.jobs.delete_many({})

    async def _ins(id_, geo, allow, sample=False):
        await db.jobs.insert_one({
            "id": id_, "canonical_key": f"test::{id_}",
            "company_name": "Test", "geo": geo,
            "eligibility_requirements":
                {"country_allowlist": allow, "requires_us_person": False},
            "is_sample": sample, "status": "live",
        })

    await _ins("j1", "Remote (US)",       ["US"])
    await _ins("j2", "Remote",            ["US"])
    await _ins("j3", "Remote — Worldwide", ["IN", "US"])
    await _ins("j4", "Remote",            None)          # indeterminate
    await _ins("j5", "Remote — worldwide", None)         # indeterminate
    # SAMPLE row — excluded even with allowlist.
    await _ins("j6", "Remote",            ["US"], sample=True)

    cov = await metrics.per_country_coverage()
    rc = cov["remote_classification_real"]
    assert rc["remote_total"] == 5, rc
    assert rc["us_only"] == 2, rc
    assert rc["india_explicit"] == 1, rc
    assert rc["indeterminate"] == 2, rc
    assert rc["country_allowlist_classified"] == 3, rc
    # Sample row counted separately.
    assert cov["sample_rows_excluded"] == 1


# ---------------------------------------------------------------- service.py wiring
def test_discovery_to_jobs_doc_persists_country_allowlist():
    """`_to_jobs_doc` must copy the row's country_allowlist into
    eligibility_requirements. Never invents; None means None."""
    from domains.discovery.service import _to_jobs_doc

    row = {
        "source_ats": "ashby", "external_id": "abc",
        "employer": "Notion", "employer_token": "notion",
        "title": "SWE", "location": "Remote — Tokyo",
        "apply_url": "https://api.ashbyhq.com/x/abc",
        "jd_text": "…", "posted_at": None, "updated_at": None,
        "fetched_at": None, "remote": True,
        "country_allowlist": ["JP", "US"],
    }
    doc = _to_jobs_doc(row, existing=None)
    er = doc["eligibility_requirements"]
    assert er["country_allowlist"] == ["JP", "US"]

    row2 = {**row, "external_id": "xyz", "country_allowlist": None}
    doc2 = _to_jobs_doc(row2, existing=None)
    assert doc2["eligibility_requirements"]["country_allowlist"] is None
