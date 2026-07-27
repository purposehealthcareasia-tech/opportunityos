"""Income velocity estimator (Phase 3 Founder Brief — Lane B "soonest money").

Deterministic. No ML, no LLM. Reads posted hourly rate from JD text when present,
falls back to salary → weekly-equivalent, falls back to None (never fabricated).

Used to sort Lane B feed by "expected first-week income" so a candidate looking
for income NOW sees the fastest-paying, most-recent postings first.

Velocity components:
  hourly_rate_usd  — parsed hourly rate ($/hr) or salary→hr
  hours_per_week   — 40 for full-time, 20 for part-time markers, 40 otherwise
  weekly_est_usd   — hourly_rate_usd * hours_per_week
  posted_days_ago  — days since first_seen or discovery.posted_at
  velocity_score   — weekly_est_usd penalized by staleness (older postings decay)
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional


# --- hourly rate parsing ----------------------------------------------------
_HOURLY_RATE = re.compile(
    r"\$\s?(\d{1,3}(?:\.\d{1,2})?)\s*(?:/|per|to|-|\s)?\s*(?:\$?(\d{1,3}(?:\.\d{1,2})?)\s*)?"
    r"(?:/|per|\s)*(?:hour|hr|hourly)",
    re.IGNORECASE,
)
_SALARY_RANGE = re.compile(
    r"\$\s?(\d{2,3})\s*[,]?(\d{3})?\s*[kK]?\s*(?:-|to|–)\s*\$?\s?(\d{2,3})\s*[,]?(\d{3})?\s*[kK]?",
)
_HOURS_PART_TIME = re.compile(r"\bpart[-\s]?time\b|\bpt\b|\bhalf[-\s]?time\b", re.IGNORECASE)


def parse_hourly_rate_usd(jd_text: str, comp: Optional[str] = None) -> Optional[float]:
    """Return an hourly USD rate parsed from JD or comp string. None if unresolved."""
    if not jd_text and not comp:
        return None
    for text in (comp or "", jd_text or ""):
        if not text:
            continue
        m = _HOURLY_RATE.search(text)
        if m:
            lo = float(m.group(1))
            hi = float(m.group(2)) if m.group(2) else None
            return (lo + hi) / 2.0 if hi else lo
    # Fall back to salary range → hourly (2080 hours/yr)
    for text in (comp or "", jd_text or ""):
        if not text:
            continue
        m = _SALARY_RANGE.search(text)
        if m:
            lo_a = int(m.group(1))
            lo_b = int(m.group(2)) if m.group(2) else 0
            hi_a = int(m.group(3))
            hi_b = int(m.group(4)) if m.group(4) else 0
            lo = lo_a * 1000 + lo_b if "k" in text.lower() or lo_b else lo_a
            hi = hi_a * 1000 + hi_b if "k" in text.lower() or hi_b else hi_a
            mid = (lo + hi) / 2.0
            return round(mid / 2080.0, 2)
    return None


def hours_per_week(employment_type: Optional[str], jd_text: str = "") -> int:
    et = (employment_type or "").lower()
    if "part" in et or "half" in et:
        return 20
    if jd_text and _HOURS_PART_TIME.search(jd_text):
        return 20
    return 40


def posted_days_ago(job: dict) -> Optional[int]:
    """Return integer days since posted_at (or first_seen). None if unknown."""
    disc = job.get("discovery") or {}
    for cand in (disc.get("posted_at"), job.get("first_seen")):
        if not cand:
            continue
        try:
            if isinstance(cand, str):
                # Handle common ISO formats
                s = cand.replace("Z", "+00:00")
                dt = datetime.fromisoformat(s)
            elif isinstance(cand, datetime):
                dt = cand
            else:
                continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            days = (datetime.now(timezone.utc) - dt).days
            return max(0, days)
        except (ValueError, TypeError):
            continue
    return None


def estimate(job: dict) -> dict:
    """Return {hourly_rate_usd, hours_per_week, weekly_est_usd, posted_days_ago,
    velocity_score} — any component may be None if unresolvable. Never invents."""
    jd = job.get("jd_text") or ""
    comp = job.get("comp") or ""
    disc = job.get("discovery") or {}
    hourly = parse_hourly_rate_usd(jd, comp)
    hpw = hours_per_week(disc.get("employment_type"), jd)
    weekly = round(hourly * hpw, 2) if hourly is not None else None
    days = posted_days_ago(job)
    # Score: weekly earnings decayed by ~2% per day since posting; None if weekly is None.
    if weekly is None:
        score = None
    else:
        decay = max(0.3, 1.0 - 0.02 * (days or 0))
        score = round(weekly * decay, 2)
    return {
        "hourly_rate_usd": hourly,
        "hours_per_week": hpw,
        "weekly_est_usd": weekly,
        "posted_days_ago": days,
        "velocity_score": score,
    }
