"""Outcome autopilot — Phase 5.3 (Founder Directive 2026-07-28).

RULE:
  Per-application ledger: viewed / response / interview / rejection /
  silence + days_to_response.

  Weekly reallocation shifting daily budget toward employers and resume
  variants that actually respond; kill-list after N consecutive
  silences — visible, reversible, and EXPLAINED in UI ("why fewer apps
  to X"). No black-box reallocation; every adjustment has a stored,
  displayable reason.

Public API:
  * record_outcome(application_id, user_id, kind, at=None) → dict
  * outcomes_for_user(user_id, since_days) → list[dict]
  * compute_group_stats(user_id, since_days=30, group_by='employer')
      → dict[group_key] → {submitted, viewed, response, interview,
                            rejection, silence, response_rate,
                            median_days_to_response}
  * reallocate_daily_budget(user_id, since_days=30,
                              min_group_submits=3) → reallocation row
  * kill_list_candidates(user_id, silence_threshold=5, silence_days=21)
      → list[{employer, consecutive_silences, last_activity_at, reason}]
  * restore_from_kill_list(user_id, employer) → void

Storage:
  * `application_outcomes` — one row per (application_id, kind, at).
  * `budget_reallocations` — one row per reallocation event with
    stored reason so the UI can render "why fewer apps to X".
  * `kill_list` — one row per (user_id, employer) currently suppressed.

Kill-list is REVERSIBLE — `restore_from_kill_list` clears the row and
records the restoration event on the audit trail.
"""
from __future__ import annotations

import logging
import statistics
import uuid
from datetime import datetime, timezone, timedelta

from core import db as core_db


log = logging.getLogger("outcome_autopilot")


# Stable outcome vocabulary — never rename without adjusting FE copy.
OUTCOME_VIEWED = "viewed"
OUTCOME_RESPONSE = "response"
OUTCOME_INTERVIEW = "interview"
OUTCOME_REJECTION = "rejection"
OUTCOME_SILENCE = "silence"
_ALL_OUTCOMES = {OUTCOME_VIEWED, OUTCOME_RESPONSE, OUTCOME_INTERVIEW,
                   OUTCOME_REJECTION, OUTCOME_SILENCE}


async def record_outcome(*, application_id: str, user_id: str, kind: str,
                            at: datetime | None = None,
                            note: str | None = None) -> dict:
    """Persist one outcome event. Kind must be in the canonical vocabulary."""
    if kind not in _ALL_OUTCOMES:
        raise ValueError(f"unknown outcome kind: {kind!r}")
    at = at or datetime.now(timezone.utc)
    doc = {
        "id": str(uuid.uuid4()),
        "application_id": application_id,
        "user_id": user_id,
        "kind": kind,
        "at": at,
        "note": note,
    }
    db = core_db.get_db()
    await db.application_outcomes.insert_one(dict(doc))
    return doc


async def _load_application_meta(user_id: str, application_ids: list[str]) -> dict:
    """Return `{application_id → {employer, resume_version_id, submitted_at}}`.
    Applications missing from DB return `{"employer": None, ...}`."""
    if not application_ids:
        return {}
    db = core_db.get_db()
    meta: dict[str, dict] = {}
    async for a in db.applications.find(
        {"id": {"$in": application_ids}, "user_id": user_id},
        {"_id": 0, "id": 1, "company_id": 1, "job_snapshot": 1,
         "materials": 1, "submitted_at": 1, "created_at": 1},
    ):
        js = a.get("job_snapshot") or {}
        employer = (a.get("company_id") or js.get("company_id")
                    or (js.get("canonical_key") or "").split("::")[0])
        meta[a["id"]] = {
            "employer": employer or "unknown",
            "resume_version_id": (a.get("materials") or {}).get("resume_version_id"),
            "submitted_at": a.get("submitted_at") or a.get("created_at"),
        }
    for aid in application_ids:
        meta.setdefault(aid, {"employer": "unknown",
                                "resume_version_id": None,
                                "submitted_at": None})
    return meta


async def compute_group_stats(user_id: str, *, since_days: int = 30,
                                 group_by: str = "employer",
                                 ) -> dict[str, dict]:
    """Aggregate outcomes into per-group counts + response_rate +
    median days-to-response.

    `group_by`: "employer" | "resume_version_id"

    Groups with zero submissions are omitted."""
    if group_by not in ("employer", "resume_version_id"):
        raise ValueError(f"invalid group_by: {group_by!r}")
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=since_days)
    db = core_db.get_db()

    # Load all outcomes in the window.
    outcomes: list[dict] = []
    async for o in db.application_outcomes.find(
        {"user_id": user_id, "at": {"$gte": since}}, {"_id": 0},
    ):
        outcomes.append(o)
    if not outcomes:
        return {}
    app_ids = sorted({o["application_id"] for o in outcomes})
    meta = await _load_application_meta(user_id, app_ids)

    per_group: dict[str, dict] = {}
    days_to_response_per_group: dict[str, list[float]] = {}
    for o in outcomes:
        m = meta.get(o["application_id"], {})
        key = m.get(group_by) or "unknown"
        stats = per_group.setdefault(key, {
            "group": key,
            "submitted": 0,
            "viewed": 0, "response": 0, "interview": 0,
            "rejection": 0, "silence": 0,
        })
        # We count `submitted` implicitly = distinct application_ids seen
        # per group. Roll this up at end.
        stats[o["kind"]] += 1
        # Days-to-response only for response/interview/rejection events.
        if o["kind"] in (OUTCOME_RESPONSE, OUTCOME_INTERVIEW, OUTCOME_REJECTION):
            submitted_at = m.get("submitted_at")
            outcome_at = o["at"]
            if submitted_at:
                if submitted_at.tzinfo is None:
                    submitted_at = submitted_at.replace(tzinfo=timezone.utc)
                if outcome_at.tzinfo is None:
                    outcome_at = outcome_at.replace(tzinfo=timezone.utc)
                delta = (outcome_at - submitted_at).total_seconds() / 86400.0
                if delta >= 0:
                    days_to_response_per_group.setdefault(key, []).append(delta)
    # Fill submitted counts.
    seen_by_group: dict[str, set[str]] = {}
    for o in outcomes:
        m = meta.get(o["application_id"], {})
        key = m.get(group_by) or "unknown"
        seen_by_group.setdefault(key, set()).add(o["application_id"])
    for key, stats in per_group.items():
        stats["submitted"] = len(seen_by_group.get(key, set()))
        responded = stats["response"] + stats["interview"] + stats["rejection"]
        stats["response_rate"] = (round(responded / stats["submitted"], 3)
                                    if stats["submitted"] else 0.0)
        lags = days_to_response_per_group.get(key) or []
        stats["median_days_to_response"] = (round(statistics.median(lags), 1)
                                              if lags else None)
    return per_group


async def reallocate_daily_budget(user_id: str, *,
                                     since_days: int = 30,
                                     min_group_submits: int = 3,
                                     ) -> dict:
    """Recompute the per-employer daily-budget allocation from observed
    response rates. Groups with < `min_group_submits` submissions are
    NOT reallocated (insufficient signal). Each adjustment is stored
    with a displayable reason."""
    now = datetime.now(timezone.utc)
    stats = await compute_group_stats(user_id, since_days=since_days,
                                         group_by="employer")
    scored = [(g, s) for g, s in stats.items()
              if s["submitted"] >= min_group_submits]
    scored.sort(key=lambda kv: (-kv[1]["response_rate"], kv[0]))

    # Simple allocation: distribute 100% proportionally to response_rate
    # among scored groups. If all rates are zero, fall back to equal
    # weighting (avoids divide-by-zero and preserves user autonomy —
    # kill-list is a separate mechanism).
    total_rate = sum(s["response_rate"] for _, s in scored) or 0.0
    allocations: list[dict] = []
    for group, s in scored:
        if total_rate > 0:
            weight = round(s["response_rate"] / total_rate, 3)
            reason = (f"response_rate={s['response_rate']:.2%} on "
                        f"{s['submitted']} apps · median_days_to_response="
                        f"{s['median_days_to_response']}")
        else:
            weight = round(1.0 / len(scored), 3) if scored else 0.0
            reason = (f"no observed responses in last {since_days} days · "
                        f"equal-weighting fallback")
        allocations.append({"group": group, "weight": weight,
                              "submitted": s["submitted"],
                              "response_rate": s["response_rate"],
                              "reason": reason})
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "computed_at": now,
        "window_days": since_days,
        "min_group_submits": min_group_submits,
        "allocations": allocations,
    }
    await core_db.get_db().budget_reallocations.insert_one(dict(doc))
    return doc


async def kill_list_candidates(user_id: str, *,
                                 silence_threshold: int = 5,
                                 silence_days: int = 21,
                                 ) -> list[dict]:
    """Return employers where the user has recorded >= silence_threshold
    consecutive silence outcomes AND no viewed/response/interview event
    in the last `silence_days`. Reversible — this DOES NOT auto-add to
    the kill list; the caller decides."""
    now = datetime.now(timezone.utc)
    stats = await compute_group_stats(user_id, since_days=silence_days,
                                         group_by="employer")
    candidates: list[dict] = []
    for employer, s in stats.items():
        # Consecutive silence proxy: silence count with zero
        # viewed+response+interview signals.
        has_signal = s["viewed"] + s["response"] + s["interview"] > 0
        if not has_signal and s["silence"] >= silence_threshold:
            candidates.append({
                "employer": employer,
                "consecutive_silences": s["silence"],
                "last_activity_at": None,
                "reason": (f"{s['silence']} silence outcomes and zero "
                             f"viewed/response/interview signals in last "
                             f"{silence_days} days"),
            })
    candidates.sort(key=lambda c: -c["consecutive_silences"])
    return candidates


async def add_to_kill_list(user_id: str, employer: str, reason: str) -> dict:
    now = datetime.now(timezone.utc)
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": user_id, "employer": employer, "reason": reason,
        "created_at": now, "restored_at": None,
    }
    db = core_db.get_db()
    # Idempotent upsert — if there's already an active kill-list row for
    # this (user, employer), leave it alone.
    existing = await db.kill_list.find_one(
        {"user_id": user_id, "employer": employer, "restored_at": None})
    if existing:
        return existing
    await db.kill_list.insert_one(dict(doc))
    return doc


async def restore_from_kill_list(user_id: str, employer: str,
                                    restored_reason: str = "user_restore",
                                    ) -> dict | None:
    """Mark the active kill-list row for (user, employer) as restored.
    Returns the updated doc, or None if there was nothing to restore."""
    db = core_db.get_db()
    now = datetime.now(timezone.utc)
    return await db.kill_list.find_one_and_update(
        {"user_id": user_id, "employer": employer, "restored_at": None},
        {"$set": {"restored_at": now, "restored_reason": restored_reason}},
        projection={"_id": 0},
        return_document=True,
    )
