"""Fixture-expectation constants — DERIVED FROM THE SEEDER, NOT HARDCODED.

Rails: **test-code only**. Zero production-code touches. Structural
approach mandated by the founder's P2a.3 flavor decision — instead of
raw number-pinning across 24 assertion sites, we import the seeder's
public constants and (for values that live inside private function
bodies) read them via `ast.literal_eval` on the seeder source. When
the seeder's shape changes, this ONE helper module either updates
automatically or fails LOUDLY at test-collection time — never 24
scattered assertions drifting silently.

If the seeder is refactored in a way that removes a value this module
depends on (e.g. renames the `entries` local in
`_seed_fixture_speed_history`), the `_read_local_literal` calls below
raise a precise error naming the missing symbol.

Every constant in this file is annotated with the seeder function it
was extracted from, so grep-ability is preserved.

CACHE-BUST NOTE (feed-geometry callers, DO NOT "fix" this backwards):
`test_fixture_acceptance_b.py::initial_feed` passes `within_mi=99997`
to force a fresh /jobs/feed compute past the 60s TTL cache (see
P2a.4 in docs/MERGE-PACKET.md). That filter — implemented in
`domains/jobs/router.py` — keeps only rows whose
`distance_from_phoenix_mi` is a numeric value <= within_mi. Remote-US
sample rows have `distance_from_phoenix_mi = None` (only Phoenix rows
have `0.0` — see `seeder.py:96,287`), so they are FILTERED OUT of the
sample-slice the test observes even though `within_mi=99997` reads
as "huge threshold, filter nothing". The Phoenix-only fail-counts
below reflect this observable reality; do not expand them to include
Remote-US rows unless the cache-bust strategy changes too.
"""
from __future__ import annotations

import ast
import inspect
from typing import Any

from domains.seeds import data as _data
from domains.seeds import seeder as _seeder
from services import employer_cap as _employer_cap_module


def _read_local_literal(func, name: str) -> Any:
    """Extract a literal assignment `name = <literal>` from inside the
    body of `func` using `ast.literal_eval`. Precise error naming the
    missing symbol on failure.
    """
    try:
        src = inspect.getsource(func)
    except OSError as e:
        raise RuntimeError(
            f"cannot inspect source of {func.__qualname__}: {e}"
        ) from e
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == name:
                    try:
                        return ast.literal_eval(node.value)
                    except Exception as e:
                        raise RuntimeError(
                            f"non-literal `{name}` in {func.__qualname__} — "
                            f"seeder refactor may have removed static shape"
                        ) from e
    raise RuntimeError(
        f"local `{name}` not found in {func.__qualname__} — seeder may have "
        f"been refactored; check tests/_fixture_expectations.py"
    )


# ---------------------------------------------------------------------------
# Public constants imported straight from the seeder module — these are
# already exported by name (no ast reading needed).
# ---------------------------------------------------------------------------
FIXTURE_EMAIL              = "fixture-ead@opportunityos.dev"        # in seeder.FIXTURE_EAD_EMAIL if exposed later
FIXTURE_BROAD_EMAIL        = _seeder.FIXTURE_BROAD_EMAIL
FIXTURE_EMPLOYER_MEMBER_EMAIL     = _seeder.FIXTURE_EMPLOYER_MEMBER_EMAIL
FIXTURE_EMPLOYER_CANONICAL_KEY    = _seeder.FIXTURE_EMPLOYER_CANONICAL_KEY

SAMPLE_COMPANY_DOMAIN   = _data.SAMPLE_COMPANY["domain"]          # "sampleco.demo"
SAMPLE_COMPANY_2_DOMAIN = _data.SAMPLE_COMPANY_2["domain"]        # "responsivedemo.demo"


# ---------------------------------------------------------------------------
# _seed_fixture_speed_history: the "entries" list of past submitted apps
# with response outcomes. Read the literal via ast so a seeder change
# either updates this module automatically OR fails at collection time.
# ---------------------------------------------------------------------------
FIXTURE_EAD_SPEED_HISTORY_ENTRIES = _read_local_literal(
    _seeder._seed_fixture_speed_history, "entries",
)
FIXTURE_EAD_SPEED_HISTORY_COUNT = len(FIXTURE_EAD_SPEED_HISTORY_ENTRIES)

# Middle-value response latency (in days) used by /jobs?sort=speed to
# compute median_days_to_response. Extract via sort so the assertion
# tracks whichever middle-tuple the seeder happens to define.
_lags = sorted([delta for (_ago, delta) in FIXTURE_EAD_SPEED_HISTORY_ENTRIES])
FIXTURE_EAD_MEDIAN_RESPONSE_LAG_DAYS = _lags[len(_lags) // 2] if _lags else None


# ---------------------------------------------------------------------------
# _seed_fixture_assisted_lane_row: creates EXACTLY 1 assisted-lane app
# on a SampleCo `is_sample=True` job (`state=assisted`). Not driven by
# a literal list — it's a single unconditional insert. Tie the constant
# to the function's existence so a refactor that removes the seed also
# updates the expectations.
# ---------------------------------------------------------------------------
FIXTURE_EAD_ASSISTED_APP_COUNT = 1 if hasattr(_seeder, "_seed_fixture_assisted_lane_row") else 0
# The assisted-lane app pins to a SampleCo job → pre-consumes 1 slot of
# the 30-day per-employer cap. This is the number of SampleCo shortlists
# a fresh test can perform before hitting 429.
FIXTURE_EAD_SAMPLECO_APPS_PRE_CONSUMED = FIXTURE_EAD_ASSISTED_APP_COUNT

# Same for the kill-list restore-CTA seed (part of Phase 5.3/5.4 fixture
# UI-visibility seeds). This is ONE hidden-outcome row on a synthetic
# employer, so it does NOT count against the SampleCo cap.
FIXTURE_EAD_KILLLIST_HIDDEN_APP_COUNT = 1 if hasattr(_seeder, "_seed_fixture_kill_list_row") else 0


# ---------------------------------------------------------------------------
# Derived roll-ups used across multiple failing assertions.
# ---------------------------------------------------------------------------
FIXTURE_EAD_TOTAL_APPS = (
    FIXTURE_EAD_SPEED_HISTORY_COUNT
    + FIXTURE_EAD_ASSISTED_APP_COUNT
    + FIXTURE_EAD_KILLLIST_HIDDEN_APP_COUNT
)

# All 3 speed-history rows have `event=response_received`. Assisted-lane
# and kill-list rows do NOT produce response outcomes.
FIXTURE_EAD_RESPONSE_OUTCOME_COUNT = FIXTURE_EAD_SPEED_HISTORY_COUNT


# ---------------------------------------------------------------------------
# EmployerCap: the test that shortlists SampleCo jobs one by one and
# expects the Nth to hit 429. N used to be 4 (cap=3), then the assisted-
# lane seed landed and pre-consumed one slot → now the FIRST FRESH
# shortlist that will 429 is one earlier. Derive that boundary here.
# ---------------------------------------------------------------------------
EMPLOYER_CAP_MAX_PER_30_DAYS = _employer_cap_module.EMPLOYER_CAP_PER_30D
EMPLOYER_CAP_FIRST_429_SAMPLECO_INDEX = (
    EMPLOYER_CAP_MAX_PER_30_DAYS - FIXTURE_EAD_SAMPLECO_APPS_PRE_CONSUMED
)   # index in a freshly-issued sequence [0,1,2,3,...] where 429 first fires


# ---------------------------------------------------------------------------
# Feed geometry — derived from SAMPLE_JOBS + SAMPLE_JOBS_RESPONSIVE.
#
# We iterate the seed literals and count fail-reasons by their `eligibility`
# sub-dict shape (offers_sponsorship / requires_us_person). Fixture-ead@
# is a US resident with EAD (needs sponsorship), so a job fails with:
#   - `no_sponsorship_offered` when eligibility.offers_sponsorship == False
#   - `requires_us_person`     when eligibility.requires_us_person == True
# (Fixture-ead is not a US citizen so ITAR fires.)
#
# PHOENIX-ONLY FILTER: The `initial_feed` fixture uses `within_mi=99997` as
# a cache-bust; that filter drops rows where `distance_from_phoenix_mi` is
# None. In the seeder (see `seeder.py:96,287`), only "Phoenix, AZ" seed
# rows get `0.0`; "Remote (US)" rows get None. So sample-slice geometry
# observable to the test is the Phoenix subset only. Remote-US samples
# exist in the DB but never surface in the test's feed view.
# ---------------------------------------------------------------------------
def _is_phoenix(job: dict) -> bool:
    """Mirror of seeder's distance-tagging rule (`seeder.py:96,287`):
    only 'Phoenix' rows carry a numeric distance_from_phoenix_mi and
    therefore survive the /jobs/feed `within_mi` filter."""
    return "Phoenix" in (job.get("geo") or "")


def _count_sample_fails(reason_key: str, expect_true_for_us_person: bool) -> int:
    n = 0
    for j in (*_data.SAMPLE_JOBS, *_data.SAMPLE_JOBS_RESPONSIVE):
        if not _is_phoenix(j):
            continue
        elig = j.get("eligibility") or {}
        if reason_key == "no_sponsorship_offered":
            if elig.get("offers_sponsorship") is False:
                n += 1
        elif reason_key == "requires_us_person":
            if elig.get("requires_us_person") is True:
                n += 1
    return n

SAMPLE_JOB_TOTAL = sum(
    1 for j in (*_data.SAMPLE_JOBS, *_data.SAMPLE_JOBS_RESPONSIVE) if _is_phoenix(j)
)
SAMPLE_JOB_FAIL_SPONSOR = _count_sample_fails("no_sponsorship_offered", False)
SAMPLE_JOB_FAIL_US_PERSON = _count_sample_fails("requires_us_person", True)
# `duplicate_application` fires against SampleCo passing jobs when the
# assisted-lane seed already created an application on them.
SAMPLE_JOB_FAIL_DUPLICATE_FROM_ASSISTED = FIXTURE_EAD_ASSISTED_APP_COUNT

# Sample-slice acceptance geometry that the /jobs endpoint reports under
# totals.excluded_by_reason (only sample-relevant keys; real-world
# `location_mismatch` / `sponsorship_unknown` are excluded from this view
# and asserted separately with min-bounds).
SAMPLE_FEED_EXCLUDED_BY_REASON = {
    "no_sponsorship_offered": SAMPLE_JOB_FAIL_SPONSOR,
    "requires_us_person": SAMPLE_JOB_FAIL_US_PERSON,
}
if SAMPLE_JOB_FAIL_DUPLICATE_FROM_ASSISTED > 0:
    SAMPLE_FEED_EXCLUDED_BY_REASON["duplicate_application"] = SAMPLE_JOB_FAIL_DUPLICATE_FROM_ASSISTED

SAMPLE_FEED_TOTAL_EXCLUDED = sum(SAMPLE_FEED_EXCLUDED_BY_REASON.values())
SAMPLE_FEED_PASSING = SAMPLE_JOB_TOTAL - SAMPLE_FEED_TOTAL_EXCLUDED


# ---------------------------------------------------------------------------
# ALL-SAMPLES variants (Phoenix + Remote-US) — for callers whose cache key
# doesn't include the `within_mi` filter, e.g. /eligibility/coverage-preview
# (no within_mi arg at all) and /jobs/feed?sort=speed (feed cache key
# includes within_mi, so sort=speed with no within_mi is a distinct cache
# key that returns unfiltered results). These endpoints see BOTH the 12
# Phoenix samples AND the 6 Remote-US samples → 18 total.
# ---------------------------------------------------------------------------
def _count_all_sample_fails(reason_key: str) -> int:
    n = 0
    for j in (*_data.SAMPLE_JOBS, *_data.SAMPLE_JOBS_RESPONSIVE):
        elig = j.get("eligibility") or {}
        if reason_key == "no_sponsorship_offered":
            if elig.get("offers_sponsorship") is False:
                n += 1
        elif reason_key == "requires_us_person":
            if elig.get("requires_us_person") is True:
                n += 1
    return n

SAMPLE_JOB_TOTAL_ALL = len(_data.SAMPLE_JOBS) + len(_data.SAMPLE_JOBS_RESPONSIVE)
SAMPLE_JOB_FAIL_SPONSOR_ALL = _count_all_sample_fails("no_sponsorship_offered")
SAMPLE_JOB_FAIL_US_PERSON_ALL = _count_all_sample_fails("requires_us_person")

SAMPLE_FEED_EXCLUDED_BY_REASON_ALL = {
    "no_sponsorship_offered": SAMPLE_JOB_FAIL_SPONSOR_ALL,
    "requires_us_person": SAMPLE_JOB_FAIL_US_PERSON_ALL,
}
if SAMPLE_JOB_FAIL_DUPLICATE_FROM_ASSISTED > 0:
    SAMPLE_FEED_EXCLUDED_BY_REASON_ALL["duplicate_application"] = SAMPLE_JOB_FAIL_DUPLICATE_FROM_ASSISTED

SAMPLE_FEED_TOTAL_EXCLUDED_ALL = sum(SAMPLE_FEED_EXCLUDED_BY_REASON_ALL.values())
SAMPLE_FEED_PASSING_ALL = SAMPLE_JOB_TOTAL_ALL - SAMPLE_FEED_TOTAL_EXCLUDED_ALL


# ---------------------------------------------------------------------------
# Kill-list restore CTA — Phase 5.3/5.4 seed. If the seeder has the helper,
# 1 hidden outcome row is created. If not, 0.
# ---------------------------------------------------------------------------
KILL_LIST_SEED_EMPLOYER_KEY = getattr(_seeder, "_FIXTURE_KILL_LIST_EMPLOYER", None)
