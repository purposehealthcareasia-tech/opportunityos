"""Phase 5e · Responds-Fast Badge.

Returns a per-employer badge map the frontend can join into feed cards.

Rails:
  * Same source data as `sort=speed` (services/outcome_autopilot::
    compute_group_stats, user-scoped only).
  * Threshold: `median_days_to_response ≤ 3` AND `≥ 3 responded`.
  * No-data employers get NO badge (never a negative badge).
  * User-scoped (cross-user history sharing is a hard rail).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from core.deps import require_consent


router = APIRouter(prefix="/api/v1/badges", tags=["badges"])


_FAST_MEDIAN_MAX_DAYS = 3     # medium ≤ this → fast
_FAST_MIN_RESPONSES = 3       # sample-size floor to earn the badge


@router.get("/responds-fast")
async def responds_fast_map(
    user: dict = Depends(require_consent("track_applications")),
):
    """Map of `employer_canonical_key` → `{fast: true, median_days,
    responded, sample_size}` for employers that qualify. Employers
    without qualifying data are OMITTED from the map (frontend renders
    NO badge for missing keys — the founder rail: never a negative
    badge)."""
    from services import outcome_autopilot as _oa
    try:
        stats = await _oa.compute_group_stats(
            user["id"], since_days=90, group_by="employer")
    except Exception:
        stats = {}

    out: dict[str, dict] = {}
    for emp_key, row in stats.items():
        median = row.get("median_days_to_response")
        submitted = row.get("submitted") or 0
        responded = (row.get("response") or 0) + \
                    (row.get("interview") or 0) + \
                    (row.get("rejection") or 0)
        if not isinstance(median, (int, float)):
            continue          # no data — omit
        if responded < _FAST_MIN_RESPONSES:
            continue          # insufficient sample — omit
        if median > _FAST_MEDIAN_MAX_DAYS:
            continue          # slower than fast — omit (never negative)
        out[emp_key] = {
            "fast": True,
            "median_days_to_response": median,
            "responded_count": responded,
            "sample_size": submitted,
        }
    return {
        "responds_fast": out,
        "count": len(out),
        "thresholds": {
            "median_days_max": _FAST_MEDIAN_MAX_DAYS,
            "min_responses": _FAST_MIN_RESPONSES,
        },
        "notice": (
            "User-scoped observed medians only. Employers not on this "
            "list have no badge — Fynd NEVER shows a 'slow' badge."
        ),
    }
