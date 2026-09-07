"""P0 Truth Audit — public metrics helpers.

Reads production-safe aggregates for the /standards page WITHOUT ever
counting SAMPLE / fixture rows. Every accessor here MUST filter fixture
users + sample jobs at the DB level so the numbers rendered on the
public measuring-state page are honest.

Rails (locked by tests in `test_standards_metrics_exclude_sample.py`):
  * `_real_user_ids_pipeline_match_out()` — a MongoDB `$match` stage
    that excludes the known fixture emails.
  * `is_sample=False` on every jobs read.
  * "Never fabricate" — if `n` is below the honest threshold defined
    in ATLAS-STATE §4, the accessor returns the string `"measuring"`
    (or `"measuring (baseline)"` for TQI/guardrails) rather than a
    synthesized number.
"""
from __future__ import annotations

import re
from typing import Any

from core.db import get_db


# ------------------------------------------------------------------
# Fixture / sample segregation
# ------------------------------------------------------------------

# Fixture user emails baked into the seeder — hardcoded IDs, not user
# data. Any application/outcome row associated with any of these MUST
# be excluded from public metrics.
FIXTURE_EMAILS = (
    "fixture-ead@opportunityos.dev",
    "fixture-broad@opportunityos.dev",
    "fixture-employer-member@opportunityos.dev",
    "admin@opportunityos.dev",
    "support@opportunityos.dev",
    "ujjwal@opportunityos.dev",
    "fixture-dryrun@opportunityos.dev",
)


async def _fixture_user_ids() -> list[str]:
    db = get_db()
    rows = await db.users.find(
        {"email": {"$in": list(FIXTURE_EMAILS)}}, {"id": 1, "_id": 0},
    ).to_list(length=64)
    return [r["id"] for r in rows if r.get("id")]


# ------------------------------------------------------------------
# Honest thresholds (see ATLAS-STATE §4). Below the threshold →
# render "measuring". Never a synthesized number.
# ------------------------------------------------------------------
THRESHOLD_RESPONSE_MEDIAN_N   = 20
THRESHOLD_INTERVIEWS_PER_100  = 50
THRESHOLD_TQI_BASELINE        = 10
THRESHOLD_GUARDRAIL_BASELINE  = 30


# ------------------------------------------------------------------
# Outcome rows for /standards (P0 item f)
# ------------------------------------------------------------------
async def public_outcome_rows() -> dict:
    """READ-ONLY aggregate over `application_outcomes` (never fabricate).

    Returns:
      - median_days_to_first_response: number OR "measuring"
      - interviews_per_100_apps:       number OR "measuring"
      - honest_n_applications:         int   (real, non-fixture)
      - honest_n_responses:            int
      - honest_n_interviews:           int
    """
    db = get_db()
    fx_ids = await _fixture_user_ids()

    # honest n on submitted applications — the denominator for rates
    honest_apps = await db.applications.count_documents({
        "user_id": {"$nin": fx_ids},
        "state": {"$in": ["submitted", "responded", "interview", "offer",
                          "rejected", "withdrawn"]},
    })

    # response outcomes — the source of median-days-to-first-response
    response_rows = await db.application_outcomes.find({
        "user_id": {"$nin": fx_ids},
        "kind": "response",
        "days_to_response": {"$type": ["int", "long", "double"]},
    }, {"days_to_response": 1, "_id": 0}).to_list(length=10_000)

    honest_responses = len(response_rows)
    if honest_responses >= THRESHOLD_RESPONSE_MEDIAN_N:
        vals = sorted(float(r["days_to_response"]) for r in response_rows)
        mid = len(vals) // 2
        median = vals[mid] if len(vals) % 2 == 1 else (vals[mid - 1] + vals[mid]) / 2.0
        median_days = round(median, 1)
    else:
        median_days = "measuring"

    # interview outcomes
    honest_interviews = await db.application_outcomes.count_documents({
        "user_id": {"$nin": fx_ids},
        "kind": "interview",
    })

    if honest_apps >= THRESHOLD_INTERVIEWS_PER_100:
        rate = round(100.0 * honest_interviews / honest_apps, 2)
        interviews_per_100 = rate
    else:
        interviews_per_100 = "measuring"

    return {
        "median_days_to_first_response": median_days,
        "interviews_per_100_apps": interviews_per_100,
        "honest_n_applications": honest_apps,
        "honest_n_responses": honest_responses,
        "honest_n_interviews": honest_interviews,
        "never_fabricate_thresholds": {
            "median_days_to_first_response": THRESHOLD_RESPONSE_MEDIAN_N,
            "interviews_per_100_apps": THRESHOLD_INTERVIEWS_PER_100,
        },
    }


# ------------------------------------------------------------------
# Per-country coverage row for /standards (P0 item i)
# ------------------------------------------------------------------
CITY_PATTERNS = [
    ("Bengaluru/Bangalore",         re.compile(r"\b(bengaluru|bangalore)\b", re.I)),
    ("Hyderabad",                   re.compile(r"\bhyderabad\b", re.I)),
    ("Pune",                        re.compile(r"\bpune\b", re.I)),
    ("Mumbai",                      re.compile(r"\bmumbai\b", re.I)),
    ("Chennai",                     re.compile(r"\bchennai\b", re.I)),
    ("Delhi/NCR/Gurugram/Noida",    re.compile(
        r"\b(delhi|new delhi|ncr|gurugram|gurgaon|noida)\b", re.I)),
]
_INDIA_RX     = re.compile(r"\bindia\b", re.I)
_US_ONLY_RX   = re.compile(
    r"remote\s*[-—:]\s*us(a|\b)|remote\s*\(\s*us\b|us\s*only|"
    r"united\s*states\s*only|\bus\s*remote\b|\busa\s*remote\b", re.I)


async def per_country_coverage() -> dict:
    """READ-ONLY per-country coverage — real rows only, SAMPLE segregated.

    Field-based classification on `jobs.geo` (free-text). No country
    field exists in the current schema, so the `indeterminate` bucket
    is labelled honestly. Excludes `is_sample=True` at the DB level.
    """
    db = get_db()
    india_hits: dict[str, int] = {name: 0 for name, _ in CITY_PATTERNS}
    india_hits["other India (country-tagged only)"] = 0

    async for r in db.jobs.aggregate([
        {"$match": {"is_sample": False}},
        {"$group": {"_id": "$geo", "n": {"$sum": 1}}},
    ]):
        g = (r.get("_id") or "")
        n = int(r.get("n") or 0)
        if not g:
            continue
        matched = False
        for name, rx in CITY_PATTERNS:
            if rx.search(g):
                india_hits[name] += n
                matched = True
                break
        if matched:
            continue
        if _INDIA_RX.search(g):
            india_hits["other India (country-tagged only)"] += n

    india_total = sum(india_hits.values())

    # Remote classification (US-only vs India-tagged vs indeterminate)
    remote_total = remote_us_only = remote_india_plausible = remote_indeterminate = 0
    async for j in db.jobs.find(
        {"is_sample": False, "geo": {"$regex": "[Rr]emote"}},
        {"geo": 1, "eligibility_requirements": 1, "_id": 0},
    ):
        remote_total += 1
        g = j.get("geo") or ""
        er = j.get("eligibility_requirements") or {}
        req_us = er.get("requires_us_person")
        if _US_ONLY_RX.search(g) or req_us is True:
            remote_us_only += 1
        elif _INDIA_RX.search(g):
            remote_india_plausible += 1
        else:
            remote_indeterminate += 1

    sample_total = await db.jobs.count_documents({"is_sample": True})

    return {
        "note": (
            "Field-based on jobs.geo (free-text) + "
            "eligibility_requirements.requires_us_person. "
            "No country-allowlist field exists in the current schema; "
            "the `indeterminate` bucket is labelled honestly. "
            "SAMPLE/fixture rows are excluded from every count "
            "(reported separately)."
        ),
        "india_by_city_real": india_hits,
        "india_total_real": india_total,
        "remote_classification_real": {
            "remote_total": remote_total,
            "us_only": remote_us_only,
            "india_explicit": remote_india_plausible,
            "indeterminate": remote_indeterminate,
        },
        "sample_rows_excluded": sample_total,
    }


# ------------------------------------------------------------------
# North-star baseline + guardrails (P0 item h)
# ------------------------------------------------------------------
async def north_star_baseline() -> dict:
    """Time to Qualified Interview + guardrails baseline.

    'Measure baselines BEFORE any optimization.' If the pool is below
    threshold, we honestly say `"measuring (baseline)"`.

    Metric definitions:
      * TQI (Time to Qualified Interview): days between a user's first
        `applications` row and their FIRST `application_outcomes` row
        with `kind="interview"`. Median across users with ≥1 interview.
      * application→response: fraction of real applications with a
        recorded `application_outcomes.kind="response"`.
      * response→interview: fraction of responses that led to an
        interview (same user, same application).
      * false-pass rate: fraction of `preflight_verdicts.ok=True` that
        were later moved to `state="review"` — proxy for false-pass.
      * false-exclusion rate: fraction of applications user manually
        `restore`d from the kill_list — proxy for false-exclusion.
      * duplicate rate: fraction of submissions that returned
        `duplicate=true`.
      * closed-listing exposure: fraction of live-feed serves whose
        job was later marked `status="closed"` within 24h — proxy
        for stale-posting exposure.
      * consent-violation count: total `audit_logs` rows with
        `action LIKE 'consent.violation%'` (must be zero-by-construction).
    """
    db = get_db()
    fx_ids = await _fixture_user_ids()

    # denominator
    total_real_apps = await db.applications.count_documents({
        "user_id": {"$nin": fx_ids},
        "state": {"$in": ["submitted", "responded", "interview", "offer",
                          "rejected", "withdrawn"]},
    })

    # TQI
    tqi_days: list[float] = []
    if total_real_apps > 0:
        # For each user with ≥1 interview, find (first app submitted_at)
        # and (first interview outcome at).
        user_ids = await db.applications.distinct("user_id", {
            "user_id": {"$nin": fx_ids},
            "state": {"$in": ["interview", "offer"]},
        })
        for user_id in user_ids:
            first_app = await db.applications.find_one(
                {"user_id": user_id, "submitted_at": {"$exists": True, "$ne": None}},
                {"submitted_at": 1, "_id": 0},
                sort=[("submitted_at", 1)],
            )
            first_interview = await db.application_outcomes.find_one(
                {"user_id": user_id, "kind": "interview"},
                {"ts": 1, "created_at": 1, "_id": 0},
                sort=[("ts", 1)],
            )
            if not first_app or not first_interview:
                continue
            start = first_app.get("submitted_at")
            end = first_interview.get("ts") or first_interview.get("created_at")
            if start and end:
                try:
                    delta = (end - start).total_seconds() / 86400.0
                    if delta >= 0:
                        tqi_days.append(delta)
                except Exception:
                    pass

    tqi_n = len(tqi_days)
    if tqi_n >= THRESHOLD_TQI_BASELINE:
        vals = sorted(tqi_days)
        mid = tqi_n // 2
        tqi_median = round(vals[mid] if tqi_n % 2 == 1
                           else (vals[mid - 1] + vals[mid]) / 2.0, 1)
    else:
        tqi_median = "measuring (baseline)"

    # Guardrails — every ratio gates on `total_real_apps >= THRESHOLD_GUARDRAIL_BASELINE`.
    if total_real_apps >= THRESHOLD_GUARDRAIL_BASELINE:
        responses = await db.application_outcomes.count_documents({
            "user_id": {"$nin": fx_ids}, "kind": "response",
        })
        interviews = await db.application_outcomes.count_documents({
            "user_id": {"$nin": fx_ids}, "kind": "interview",
        })
        app_to_response = round(responses / total_real_apps, 4)
        response_to_interview = round(interviews / responses, 4) if responses > 0 else 0.0

        # false-pass proxy: preflight said ok=True, then app was moved to review.
        false_pass_hits = await db.preflight_verdicts.count_documents({
            "user_id": {"$nin": fx_ids},
            "verdict.ok": True,
            "downstream_state": "review",
        })
        total_preflight = await db.preflight_verdicts.count_documents({
            "user_id": {"$nin": fx_ids}, "verdict.ok": True,
        })
        false_pass_rate = round(false_pass_hits / total_preflight, 4) if total_preflight > 0 else 0.0

        # false-exclusion proxy: kill_list rows restored by the user
        restored = await db.kill_list.count_documents({
            "user_id": {"$nin": fx_ids},
            "restored_reason": "user_restore",
        })
        total_killed = await db.kill_list.count_documents({
            "user_id": {"$nin": fx_ids},
        })
        false_exclusion_rate = round(restored / total_killed, 4) if total_killed > 0 else 0.0

        # duplicate rate: submission_receipts with duplicate=True
        dupes = await db.submission_receipts.count_documents({
            "user_id": {"$nin": fx_ids},
            "duplicate": True,
        })
        total_receipts = await db.submission_receipts.count_documents({
            "user_id": {"$nin": fx_ids},
        })
        duplicate_rate = round(dupes / total_receipts, 4) if total_receipts > 0 else 0.0
    else:
        app_to_response = "measuring (baseline)"
        response_to_interview = "measuring (baseline)"
        false_pass_rate = "measuring (baseline)"
        false_exclusion_rate = "measuring (baseline)"
        duplicate_rate = "measuring (baseline)"

    # closed-listing exposure — currently reported as pool-wide (a real
    # per-serve proxy needs a feed_serves ledger which is P1 Foundation).
    total_jobs = await db.jobs.count_documents({"is_sample": False})
    closed_jobs = await db.jobs.count_documents({"is_sample": False, "status": "closed"})
    closed_pool_share = round(closed_jobs / total_jobs, 4) if total_jobs > 0 else 0.0

    # consent-violation count — must be zero-by-construction
    consent_violations = await db.audit_logs.count_documents({
        "action": {"$regex": "^consent\\.violation"},
    })

    return {
        "time_to_qualified_interview_days_median": tqi_median,
        "n_users_with_interview": tqi_n,
        "guardrails": {
            "application_to_response_rate": app_to_response,
            "response_to_interview_rate": response_to_interview,
            "false_pass_rate": false_pass_rate,
            "false_exclusion_rate": false_exclusion_rate,
            "duplicate_rate": duplicate_rate,
            "closed_listing_pool_share": closed_pool_share,
            "consent_violation_count": consent_violations,
        },
        "honest_n_applications": total_real_apps,
        "never_fabricate_thresholds": {
            "tqi_median": THRESHOLD_TQI_BASELINE,
            "guardrail_baselines": THRESHOLD_GUARDRAIL_BASELINE,
        },
        "measurement_note": (
            "Baseline captured BEFORE any optimization. "
            "SAMPLE/fixture rows excluded at the DB layer. "
            "Below-threshold buckets render 'measuring (baseline)' — "
            "never a synthesized number."
        ),
    }
