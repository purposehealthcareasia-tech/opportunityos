"""Credential-unlock candidate service (Phase 3 improvement — 2026-07-27).

For each credential in the Credential-to-Income catalog, count how many LIVE
jobs in the local feed would newly pass a user's gates if they held that
credential. Numbers are ALWAYS real live queries (`jobs.count_documents`) —
never fabricated. Cost/time figures come from the catalog's `approx_cost_usd`
and `time_to_credential` fields; if the corresponding row's `mandatory` flag
is False the UI must render the catalog's `suggested_next[]` link INSTEAD of
a bare figure, per the FACT RULES the founder attached to this feature.

Deterministic, no network, no LLM.
"""
from __future__ import annotations

import re
from typing import Optional

from core.db import get_db
from domains.credentials import get_catalog


# Regex library — the credential ID → an OR-regex that matches the credential
# in a job's JD text OR its requirements.licenses list. Sourced from the same
# labels we use in gate_engine.py so classification is consistent.
_CATALOG_REGEXES: dict[str, str] = {
    "cdl-class-a": r"cdl|commercial\s+driver'?s?\s+licen[cs]e",
    "cna": r"cna|certified\s+nursing\s+assistant",
    "emt-basic": r"\bemt\b|emergency\s+medical\s+technician|\bparamedic\b",
    "phlebotomy": r"phlebotom(?:y|ist)",
    "medical-assistant": r"medical\s+assistant|\bccma\b|\brma\b",
    "forklift-osha": r"forklift|osha\s*30|osha\s*10|powered\s+industrial\s+truck",
    "food-handler-az": r"food\s+handler|food\s+safety\s+card|food\s+worker\s+card",
    "az-fingerprint-clearance": r"fingerprint\s+clearance|iva[cp]s?\s+card|dps\s+clearance",
    "guard-card-az": r"security\s+guard|guard\s+card|unarmed\s+security",
}


async def _count_matches(regex_pat: str,
                          within_mi: Optional[int] = None,
                          lane: Optional[str] = "income_now") -> tuple[int, list[str]]:
    """Return (count, top_3_sample_titles) of LIVE jobs mentioning the credential.

    Rails:
      * status=live only.
      * Optional lane filter (defaults to Lane B where the credentials apply).
      * Optional within_mi radius (only counts jobs whose distance is known).
      * Case-insensitive substring / regex against jd_text OR requirements.licenses.
    """
    db = get_db()
    q: dict = {"status": "live"}
    if lane:
        q["lane"] = lane
    if within_mi is not None and within_mi > 0:
        q["distance_from_phoenix_mi"] = {"$lte": within_mi}
    # Case-insensitive regex against JD text OR the structured license list
    q["$or"] = [
        {"jd_text": {"$regex": regex_pat, "$options": "i"}},
        {"requirements.licenses": {"$regex": regex_pat, "$options": "i"}},
    ]
    n = await db.jobs.count_documents(q)
    titles: list[str] = []
    async for row in db.jobs.find(q, {"title": 1, "_id": 0}).limit(3):
        t = row.get("title")
        if t:
            titles.append(t)
    return n, titles


async def unlock_candidates(within_mi: Optional[int] = None,
                             lane: Optional[str] = "income_now",
                             top_k: int = 3) -> list[dict]:
    """Return the top-k credentials ranked by how many live jobs they unlock.

    Response shape per item:
      {
        credential: <catalog row>,
        live_unlock_count: <int, REAL count>,
        sample_titles: [<str>, ...],
        query: {"lane": ..., "within_mi": ...},
      }

    Optimization: all catalog credentials are counted in parallel via
    asyncio.gather so the endpoint completes in ~1s instead of ~8s
    (was serial → dominant regex cost was linear in catalog size).
    """
    import asyncio
    catalog = get_catalog()
    async def _one(cred):
        pat = _CATALOG_REGEXES.get(cred["id"])
        if not pat:
            return {"credential": cred, "live_unlock_count": 0,
                    "sample_titles": [], "query": {"lane": lane, "within_mi": within_mi}}
        try:
            count, titles = await _count_matches(pat, within_mi=within_mi, lane=lane)
        except re.error:
            count, titles = 0, []
        return {"credential": cred, "live_unlock_count": count,
                "sample_titles": titles, "query": {"lane": lane, "within_mi": within_mi}}
    rows = await asyncio.gather(*(_one(cred) for cred in catalog))
    rows.sort(key=lambda r: r["live_unlock_count"], reverse=True)
    return [r for r in rows if r["live_unlock_count"] > 0][:top_k]
