"""Phase 2 — INTELLIGENCE VISIBLE. Read-only outcome analytics.

All three endpoints are:
  * `track_applications` consent-gated
  * READ-ONLY — no writes, no side-effects
  * Aggregations of the immutable `outcomes` / `applications` /
    `application_outcomes` ledgers — never fabricated numbers
  * Descriptive-only copy (rejection-autopsy in particular) — no
    accusations of any employer

Endpoints
---------
GET /api/v1/outcomes/sparklines
    Twin read-only sparklines:
      * `employer_response_drift`  — last 8 weeks × median days-from-app
                                     to first `response` event
      * `aab_lag`                  — last 14 days × avg latency from
                                     job.discovered_at → application.created_at

GET /api/v1/outcomes/digest/weekly
    Last-7-days digest, in-app render.  Structured JSON only — email
    dispatch is behind the `WEEKLY_DIGEST_EMAIL_ENABLED` env flag and is
    OFF by default in every env (preview + prod).  The founder flips
    the flag at DNS+live time.

GET /api/v1/outcomes/rejection-autopsy
    Per-employer rejection pattern.  Categorizes rejection outcome
    `note`s into stable buckets and returns a per-employer histogram.
    Copy stays DESCRIPTIVE ("responded with a rejection", never
    "unfair" / "biased").
"""
from __future__ import annotations
import os
import statistics
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from core.db import get_db
from core.deps import require_consent

router = APIRouter(prefix="/api/v1/outcomes", tags=["outcomes-intelligence"])


# ----------------------------------------------------------------------
# 1 · Sparklines
# ----------------------------------------------------------------------

RESPONSE_WEEKS = 8
AAB_DAYS = 14


async def _median_response_days_by_week(user_id: str) -> list[dict]:
    """For each of the last `RESPONSE_WEEKS` weeks, compute the median
    days-from-application-created-to-first-response-event across the
    user's applications that hit a response IN that week.
    Weeks are UTC-anchored, oldest-first."""
    db = get_db()
    now = datetime.now(timezone.utc)
    # Anchor the newest bucket end on now, walk backwards in 7-day steps.
    buckets: list[dict] = []
    for i in range(RESPONSE_WEEKS - 1, -1, -1):
        end = now - timedelta(days=7 * i)
        start = end - timedelta(days=7)
        buckets.append({
            "week_start": start.date().isoformat(),
            "week_end": end.date().isoformat(),
            "median_days_to_response": None,
            "sample_size": 0,
        })

    # Response events for this user in the window.
    horizon = now - timedelta(days=7 * RESPONSE_WEEKS)
    cur = db.outcomes.find(
        {"user_id": user_id, "event": "response", "ts": {"$gte": horizon}},
        {"_id": 0, "application_id": 1, "ts": 1},
    ).sort("ts", 1)
    seen: dict[str, dict] = {}  # first response only per application
    async for o in cur:
        app_id = o["application_id"]
        if app_id in seen:
            continue
        seen[app_id] = o

    # Pull the corresponding applications.
    if not seen:
        return buckets
    app_ids = list(seen.keys())
    apps: dict[str, dict] = {}
    async for a in db.applications.find(
        {"id": {"$in": app_ids}, "user_id": user_id},
        {"_id": 0, "id": 1, "created_at": 1},
    ):
        apps[a["id"]] = a

    # Bin.
    for app_id, resp in seen.items():
        a = apps.get(app_id)
        if not a or not a.get("created_at"):
            continue
        submitted_at = a["created_at"]
        if submitted_at.tzinfo is None:
            submitted_at = submitted_at.replace(tzinfo=timezone.utc)
        response_ts = resp["ts"]
        if response_ts.tzinfo is None:
            response_ts = response_ts.replace(tzinfo=timezone.utc)
        delta_days = (response_ts - submitted_at).total_seconds() / 86400.0
        if delta_days < 0:
            continue
        for b in buckets:
            b_end = datetime.fromisoformat(b["week_end"]).replace(tzinfo=timezone.utc)
            b_start = datetime.fromisoformat(b["week_start"]).replace(tzinfo=timezone.utc)
            if b_start <= response_ts < b_end:
                b.setdefault("_samples", []).append(delta_days)
                break

    for b in buckets:
        s = b.pop("_samples", [])
        if s:
            b["median_days_to_response"] = round(statistics.median(s), 2)
            b["sample_size"] = len(s)
    return buckets


async def _aab_lag_by_day(user_id: str) -> list[dict]:
    """Per-day avg latency from `job.discovered_at` → `application.created_at`.
    Returns AAB_DAYS buckets oldest-first."""
    db = get_db()
    now = datetime.now(timezone.utc)
    buckets: list[dict] = []
    for i in range(AAB_DAYS - 1, -1, -1):
        d_end = now - timedelta(days=i)
        d_start = d_end - timedelta(days=1)
        buckets.append({
            "day_start": d_start.date().isoformat(),
            "day_end": d_end.date().isoformat(),
            "avg_lag_hours": None,
            "sample_size": 0,
        })

    horizon = now - timedelta(days=AAB_DAYS)
    apps: list[dict] = []
    async for a in db.applications.find(
        {"user_id": user_id, "created_at": {"$gte": horizon},
          "source": {"$in": ["apply_at_birth", "wave", "aab", "standing_wave"]}},
        {"_id": 0, "id": 1, "job_id": 1, "created_at": 1},
    ).sort("created_at", 1):
        apps.append(a)
    if not apps:
        return buckets

    # Load the discovered_at of each corresponding job.
    job_ids = list({a["job_id"] for a in apps if a.get("job_id")})
    disc: dict[str, datetime] = {}
    async for j in db.jobs.find(
        {"id": {"$in": job_ids}},
        {"_id": 0, "id": 1, "discovered_at": 1},
    ):
        if j.get("discovered_at"):
            disc[j["id"]] = j["discovered_at"]

    for a in apps:
        dt = disc.get(a.get("job_id"))
        if not dt:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        created = a["created_at"]
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        lag_hours = (created - dt).total_seconds() / 3600.0
        if lag_hours < 0:
            continue
        for b in buckets:
            d_end = datetime.fromisoformat(b["day_end"]).replace(tzinfo=timezone.utc)
            d_start = datetime.fromisoformat(b["day_start"]).replace(tzinfo=timezone.utc)
            if d_start <= created < d_end:
                b.setdefault("_samples", []).append(lag_hours)
                break

    for b in buckets:
        s = b.pop("_samples", [])
        if s:
            b["avg_lag_hours"] = round(sum(s) / len(s), 2)
            b["sample_size"] = len(s)
    return buckets


@router.get("/sparklines")
async def sparklines(
    user: dict = Depends(require_consent("track_applications")),
):
    """Twin read-only sparklines. Returns two series + honest 'no-data' bits.

    Never fabricates a number when the sample-size for a bucket is 0 —
    that bucket surfaces `median_days_to_response: null` / `avg_lag_hours: null`
    and the UI renders a gap in the sparkline (mirror of Phase 1
    "no response data yet" invariant).
    """
    resp_series = await _median_response_days_by_week(user["id"])
    aab_series = await _aab_lag_by_day(user["id"])
    return {
        "employer_response_drift": {
            "buckets": resp_series,
            "unit": "days",
            "window": f"last {RESPONSE_WEEKS} weeks",
            "note": (
                "Median days from application submitted to first response "
                "event. Buckets with sample_size=0 are honest gaps — never "
                "interpolated."
            ),
        },
        "aab_lag": {
            "buckets": aab_series,
            "unit": "hours",
            "window": f"last {AAB_DAYS} days",
            "note": (
                "Average latency from job discovered to application queued "
                "by Apply-at-Birth. Empty days = no AAB activity that day."
            ),
        },
    }


# ----------------------------------------------------------------------
# 2 · Weekly digest (in-app; email dispatch behind a config flag)
# ----------------------------------------------------------------------

@router.get("/digest/weekly")
async def weekly_digest(
    user: dict = Depends(require_consent("track_applications")),
):
    """Last-7-day roll-up. In-app only for now. Email dispatch is behind
    `WEEKLY_DIGEST_EMAIL_ENABLED` (default OFF everywhere)."""
    db = get_db()
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=7)

    apps_submitted = await db.applications.count_documents({
        "user_id": user["id"],
        "created_at": {"$gte": since},
    })
    # Event counts from the immutable outcomes ledger.
    events = {"response": 0, "interview_request": 0, "interview_scheduled": 0,
              "rejected": 0, "offer": 0}
    async for o in db.outcomes.find(
        {"user_id": user["id"], "ts": {"$gte": since}},
        {"_id": 0, "event": 1},
    ):
        e = o.get("event")
        if e in events:
            events[e] += 1

    # Response-time samples (this week only, first-response-per-app).
    response_samples: list[float] = []
    seen_apps: set[str] = set()
    async for o in db.outcomes.find(
        {"user_id": user["id"], "event": "response", "ts": {"$gte": since}},
        {"_id": 0, "application_id": 1, "ts": 1},
    ).sort("ts", 1):
        aid = o["application_id"]
        if aid in seen_apps:
            continue
        seen_apps.add(aid)
        app = await db.applications.find_one(
            {"id": aid, "user_id": user["id"]}, {"_id": 0, "created_at": 1})
        if not app or not app.get("created_at"):
            continue
        created = app["created_at"]
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        ts = o["ts"]
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        d = (ts - created).total_seconds() / 86400.0
        if d >= 0:
            response_samples.append(d)

    median_response = (
        round(statistics.median(response_samples), 2)
        if response_samples else None
    )

    email_enabled = (
        os.environ.get("WEEKLY_DIGEST_EMAIL_ENABLED", "").lower() == "true"
    )
    return {
        "period": {
            "start": since.date().isoformat(),
            "end": now.date().isoformat(),
        },
        "applications_submitted": apps_submitted,
        "events": events,
        "median_response_days": median_response,
        "response_sample_size": len(response_samples),
        "email_dispatch": {
            "enabled": email_enabled,
            "note": (
                "Email dispatch stays OFF until the founder flips "
                "WEEKLY_DIGEST_EMAIL_ENABLED at DNS+live time. In-app "
                "render is safe to show now."
            ),
        },
    }


# ----------------------------------------------------------------------
# 3 · Rejection autopsy (descriptive only)
# ----------------------------------------------------------------------

REJECTION_BUCKETS = [
    ("no_reason_given", ("no reason", "unspecified", "no note")),
    ("rejection_after_screen", ("phone screen", "screening call", "screen ")),
    ("rejection_after_interview", ("interview", "final round", "hiring loop")),
    ("rejection_experience_mismatch", ("years of experience", "seniority",
                                          "not senior enough", "not enough years")),
    ("rejection_credential_mismatch", ("degree", "credential", "qualification",
                                          "certification", "license")),
    ("rejection_location_mismatch", ("location", "remote", "onsite", "relocate")),
    ("rejection_visa_or_status", ("visa", "sponsorship", "citizenship",
                                     "authorization", "work permit")),
]


def _categorize(note: str | None) -> str:
    n = (note or "").lower()
    if not n:
        return "no_reason_given"
    for bucket, needles in REJECTION_BUCKETS:
        if any(needle in n for needle in needles):
            return bucket
    return "other"


@router.get("/rejection-autopsy")
async def rejection_autopsy(
    user: dict = Depends(require_consent("track_applications")),
):
    """Per-employer categorized rejection histogram. Descriptive-only.

    NEVER surfaces accusatory copy — the founder rail is: describe what
    happened, do not judge the employer.
    """
    db = get_db()
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=180)  # ~6 months

    # Pull rejected outcomes joined with application → employer.
    rejections: list[dict] = []
    async for o in db.outcomes.find(
        {"user_id": user["id"], "event": "rejected", "ts": {"$gte": since}},
        {"_id": 0, "application_id": 1, "note": 1, "ts": 1},
    ).sort("ts", -1):
        rejections.append(o)
    if not rejections:
        return {
            "total_rejections": 0,
            "employers": [],
            "categories": {},
            "note": (
                "No rejection outcomes in the last 180 days. Descriptive "
                "surface — no employer is judged; this is your ledger."
            ),
        }

    app_ids = list({r["application_id"] for r in rejections})
    apps: dict[str, dict] = {}
    async for a in db.applications.find(
        {"id": {"$in": app_ids}, "user_id": user["id"]},
        {"_id": 0, "id": 1, "employer": 1, "company_name": 1, "job_id": 1},
    ):
        apps[a["id"]] = a

    # Aggregate.
    category_totals: dict[str, int] = {}
    by_employer: dict[str, dict] = {}
    for r in rejections:
        cat = _categorize(r.get("note"))
        category_totals[cat] = category_totals.get(cat, 0) + 1
        a = apps.get(r["application_id"]) or {}
        emp = (a.get("employer")
               or a.get("company_name")
               or "unspecified_employer")
        row = by_employer.setdefault(emp, {
            "employer": emp,
            "count": 0,
            "categories": {},
            "most_recent_ts": None,
        })
        row["count"] += 1
        row["categories"][cat] = row["categories"].get(cat, 0) + 1
        ts = r["ts"]
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        prev = row["most_recent_ts"]
        prev_dt = None if prev is None else datetime.fromisoformat(prev)
        if prev_dt is None or ts > prev_dt:
            row["most_recent_ts"] = ts.isoformat()

    emp_rows = sorted(
        by_employer.values(),
        key=lambda r: (-r["count"], r["employer"]),
    )
    return {
        "total_rejections": len(rejections),
        "categories": category_totals,
        "employers": emp_rows,
        "note": (
            "Descriptive-only surface. Categorized from your own outcome "
            "notes; no external interpretation is added, and no employer "
            "is judged. Empty note → `no_reason_given`."
        ),
    }
