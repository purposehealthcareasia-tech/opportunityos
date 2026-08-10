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
# We iterate the seed literals and count fail-reasons by their `eligibility`
# sub-dict shape (offers_sponsorship / requires_us_person). Fixture-ead@
# is a US resident with EAD (needs sponsorship), so a job fails with:
#   - `no_sponsorship_offered` when eligibility.offers_sponsorship == False
#   - `requires_us_person`     when eligibility.requires_us_person == True
# (Fixture-ead is not a US citizen so ITAR fires.)
# ---------------------------------------------------------------------------
def _count_sample_fails(reason_key: str, expect_true_for_us_person: bool) -> int:
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

SAMPLE_JOB_TOTAL = len(_data.SAMPLE_JOBS) + len(_data.SAMPLE_JOBS_RESPONSIVE)
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
# Kill-list restore CTA — Phase 5.3/5.4 seed. If the seeder has the helper,
# 1 hidden outcome row is created. If not, 0.
# ---------------------------------------------------------------------------
KILL_LIST_SEED_EMPLOYER_KEY = getattr(_seeder, "_FIXTURE_KILL_LIST_EMPLOYER", None)
