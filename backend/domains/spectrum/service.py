"""Phase 6b · Auto-spectrum suggestion service.

Reads the caller's Passport (approved-only claim rows) and infers a
starter spectrum: titles from role/experience claims, radius default,
pay floor from verified compensation-history ONLY (never invented).

Rails:
* Suggestions come ONLY from claims where `status="approved" AND
  user_approved=True AND superseded_by is None`. Unattested / rejected /
  historical claims are ignored.
* `pay_floor` is `None` unless the user has verified compensation-history
  rows. Never a made-up placeholder. Rationale surfaced honestly in
  `rationale.pay_floor`.
* Radius default is `25` miles (matches existing /jobs/feed default).
* Titles capped at 5, ordered by claim recency (most-recent first).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from core.db import get_db


DEFAULT_RADIUS_MI = 25
MAX_SUGGESTED_TITLES = 5


def _extract_title(claim_value: dict) -> Optional[str]:
    """Claim `value` dict may hold `role`, `title`, or the raw
    experience string. Return the first non-empty match."""
    if not claim_value:
        return None
    for key in ("role", "title", "name"):
        v = claim_value.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _extract_comp_row(claim_value: dict) -> Optional[dict]:
    """Compensation-history rows have shape {annual_usd, currency,
    verified, employer, start_year, end_year}. Return the row if it
    looks well-formed, else None."""
    if not isinstance(claim_value, dict):
        return None
    amt = claim_value.get("annual_usd") or claim_value.get("amount") or claim_value.get("base")
    if amt is None:
        return None
    try:
        amt = int(amt)
    except (ValueError, TypeError):
        return None
    if amt <= 0:
        return None
    return {"annual_usd": amt,
            "verified": bool(claim_value.get("verified", False)),
            "end_year": claim_value.get("end_year") or claim_value.get("year")}


async def suggest_spectrum(user_id: str) -> dict:
    """Return `{titles, radius_mi, pay_floor, rationale}` where all
    fields are either honestly inferred from the Passport or explicitly
    documented as absent."""
    db = get_db()
    # Approved-only, not-superseded claims.
    query = {
        "user_id": user_id,
        "status": "approved",
        "user_approved": True,
        "$or": [{"superseded_by": None}, {"superseded_by": {"$exists": False}}],
    }
    claims = []
    async for c in db.claims.find(query, {"_id": 0}).sort("updated_at", -1):
        claims.append(c)

    # Titles: from claims typed role, experience, or job-like.
    titles: list[str] = []
    seen: set[str] = set()
    for c in claims:
        if c.get("type") not in ("role", "experience", "employment", "job"):
            continue
        t = _extract_title(c.get("value") or {})
        if t and t.lower() not in seen:
            titles.append(t)
            seen.add(t.lower())
        if len(titles) >= MAX_SUGGESTED_TITLES:
            break

    # Pay floor: median of last-2-years VERIFIED compensation rows.
    cutoff_year = datetime.now(timezone.utc).year - 2
    verified_comp: list[int] = []
    for c in claims:
        if c.get("type") not in ("compensation", "compensation_history", "pay"):
            continue
        row = _extract_comp_row(c.get("value") or {})
        if not row:
            continue
        if not row["verified"]:
            continue
        ey = row.get("end_year")
        if ey is None or (isinstance(ey, int) and ey < cutoff_year):
            continue
        verified_comp.append(row["annual_usd"])

    pay_floor: Optional[int] = None
    if verified_comp:
        verified_comp.sort()
        n = len(verified_comp)
        pay_floor = verified_comp[n // 2] if n % 2 else (verified_comp[n // 2 - 1] + verified_comp[n // 2]) // 2
        pay_rationale = f"median of {n} verified compensation-history rows in the last 2 years"
    else:
        pay_rationale = "no_verified_history"

    return {
        "titles": titles,
        "radius_mi": DEFAULT_RADIUS_MI,
        "pay_floor": pay_floor,
        "rationale": {
            "titles_source": (
                f"{len(titles)} approved role/experience claims" if titles
                else "no_approved_role_or_experience_claims"
            ),
            "radius_source": "default (25 mi) — edit anytime",
            "pay_floor": pay_rationale,
        },
        "honest_label": "suggested from your Passport — edit anytime",
    }
