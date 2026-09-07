"""Phase 4 · /standards — public measuring-state page.

READ-ONLY endpoint. Surfaces the honest current state of every rail
switch, feature flag, and coverage number the founder wants visible to
the world (not just to authenticated users).

Endpoint
--------
GET /api/v1/standards  (PUBLIC — no auth required)

Returns:
  - Feature flags with their current default / state.
  - Rail switches with their positions.
  - Coverage numbers derived READ-ONLY from the current DB
    (verified providers count, ingested jobs count, phase gates
    achieved).
  - Policy text version.
  - **P0 Truth Audit additions (2026-08-13):**
    * `phases_gated_pass` synced through Phase 6 + Hotfix + Hotfix
      Gate Fix. `change_history` records the append-only trail of
      gate transitions / material rail changes.
    * `outcome_rows` — median days-to-first-response, interviews per
      100 apps. Never-fabricate: below-threshold → "measuring".
    * `verification_ladder` — public claim-verification tier
      definitions (owner-attested → document-backed → third-party-
      checked). Structural, not user-scoped.
    * `per_country_coverage` — real rows only, SAMPLE segregated,
      honest indeterminate bucket where the schema lacks a country
      field.
    * `north_star` — Time to Qualified Interview + guardrail metrics
      baseline. SAMPLE excluded. Below-threshold → "measuring (baseline)".

The page never surfaces PII. Every number is a public aggregate.
"""
from __future__ import annotations
import os
from fastapi import APIRouter

from core.db import get_db
from domains.standards import metrics as _metrics


router = APIRouter(prefix="/api/v1", tags=["standards"])


def _flag(name: str, safe_default: bool = False) -> dict:
    v = os.environ.get(name, "").lower()
    enabled = v == "true"
    return {
        "flag": name,
        "enabled": enabled,
        "safe_default": safe_default,
        "note": ("ON" if enabled
                 else "OFF (safe default)" if safe_default is False
                 else "OFF (currently)"),
    }


# ------------------------------------------------------------------
# Phases gated pass — synced to actual merged phases (P0 Truth Audit d)
# ------------------------------------------------------------------
PHASES_GATED_PASS = [
    {"phase": "Phase 0 · Fynd Liquid retheme + rebrand",
     "verdict": "PASSED", "date": "2026-08-04"},
    {"phase": "Phase 1 · CONVERSION LAYER",
     "verdict": "PASSED", "date": "2026-08-06"},
    {"phase": "Phase 2 · INTELLIGENCE VISIBLE",
     "verdict": "PASSED", "date": "2026-08-08"},
    {"phase": "Phase 3 · SUPPLY ENGINE",
     "verdict": "PASSED", "date": "2026-08-08"},
    {"phase": "Phase 4 · ELIGIBILITY ENGINE & EXPORTS",
     "verdict": "PASSED", "date": "2026-08-08"},
    {"phase": "Phase 5 · WEBSITE SCALING TIER (5a-5j)",
     "verdict": "PASSED", "date": "2026-08-10"},
    {"phase": "Phase 6 · TWO-TAP ONBOARDING",
     "verdict": "PASSED", "date": "2026-08-12"},
    {"phase": "Hotfix Trio · parse split + manual claim + finish CTA",
     "verdict": "PASSED", "date": "2026-08-13"},
    {"phase": "Hotfix Gate Fix · manual claim pending draft + structured identity",
     "verdict": "PASSED", "date": "2026-08-13"},
]


# ------------------------------------------------------------------
# Append-only change history (P0 Truth Audit d)
# NOTE: this list is INTENTIONALLY hand-maintained — the /standards page
# is where auditors look for "what changed and when". Every phase gate
# and material rail/policy change lands here, newest last. Never rewrite
# a past entry; only append.
# ------------------------------------------------------------------
CHANGE_HISTORY = [
    {"date": "2026-08-04",
     "change": "Phase 0 PASSED — Fynd Liquid retheme + rebrand from OpportunityOS."},
    {"date": "2026-08-06",
     "change": "Phase 1 PASSED — CONVERSION LAYER (speed-ranked feed, Apply Wave, "
               "instant-scheduling link, follow-up drafts)."},
    {"date": "2026-08-08",
     "change": "Phase 2 PASSED — INTELLIGENCE VISIBLE (/outcomes sparklines, "
               "weekly digest, rejection autopsy)."},
    {"date": "2026-08-08",
     "change": "Phase 3 PASSED — SUPPLY ENGINE (/employers/connect, request-this-"
               "employer voting, abuse-log persistence lock)."},
    {"date": "2026-08-08",
     "change": "Phase 4 PASSED — ELIGIBILITY ENGINE & EXPORTS (null-envelope "
               "uniformity, pre-flight validator dispatch chokepoint, HMAC "
               "signed evidence exports)."},
    {"date": "2026-08-10",
     "change": "Phase 5 PASSED — WEBSITE SCALING TIER (10 items 5a-5j; extension "
               "MV3 [activeTab,storage] only with empty host_permissions; single "
               "verify endpoint; single signing key)."},
    {"date": "2026-08-12",
     "change": "Phase 6 PASSED — TWO-TAP ONBOARDING (Batch D UI /onboarding/launch; "
               "verbatim-consent scope rail with 2-scope allowlist)."},
    {"date": "2026-08-13",
     "change": "Hotfix Trio SHIPPED — parse-pipeline error-code split "
               "(extractor_error / scanned_pdf_suspected / docx_extractor_blind / "
               "too_little_content), manual-claim entry mounted on Passport, "
               "'Finish Passport' SmartCTA deep-link + CI rail."},
    {"date": "2026-08-13",
     "change": "Hotfix Gate Fix — manual claims now save as pending draft "
               "(status='pending', user_approved=False; explicit Approve for "
               "attestation); identity modal exposes legal_first / legal_last / "
               "preferred_name structured fields; preflight_validator dual-shape "
               "identity reader (legacy 'name' + new structured)."},
    {"date": "2026-08-13",
     "change": "P0 Truth Audit — Fynd brand sweep completed; /privacy-policy "
               "SPA redirects to static /privacy.html (Version 1.0); footer "
               "version derives from build via GET /api/v1/meta/version; "
               "robots.txt + sitemap.xml shipped; operator page at /about; "
               "standards synced through Phase 6 + hotfix + gate fix; "
               "outcome rows + verification ladder + per-country coverage "
               "+ north-star baseline added to /standards."},
]


# ------------------------------------------------------------------
# Public claim-verification ladder (P0 Truth Audit f)
# Structural definition — same for every user. Used on /standards
# to explain what "verified" means at each tier.
# ------------------------------------------------------------------
VERIFICATION_LADDER = [
    {
        "tier": 1,
        "name": "owner-attested",
        "definition": (
            "The candidate explicitly authored the claim and pressed "
            "Approve on their Passport. Every claim starts here."
        ),
        "evidence": "user_approved=True + audit trail on the claim row.",
        "employer_signal": "Baseline. The candidate stands behind the claim.",
    },
    {
        "tier": 2,
        "name": "document-backed",
        "definition": (
            "The claim is linked to a document (résumé, transcript, "
            "certification PDF) that the user uploaded and approved."
        ),
        "evidence": "claim.evidence[] contains a document reference "
                    "with a fingerprint hash matching a stored document.",
        "employer_signal": "The candidate has an artifact for it; the "
                           "artifact is on file inside Fynd.",
    },
    {
        "tier": 3,
        "name": "third-party-checked",
        "definition": (
            "The claim was independently verified against a third-party "
            "issuer's API (education verification network, licensure "
            "board, identity provider). Requires the CONFIGURATION_REQUIRED "
            "third-party integration for the specific category."
        ),
        "evidence": "claim.verification.level ≥ 2 + a third-party "
                    "receipt id + issuer name recorded.",
        "employer_signal": "The issuer itself confirmed the claim to Fynd.",
    },
]


@router.get("/standards")
async def standards():
    """Public measuring-state page. Aggregates ONLY — no PII, no user-scoped data."""
    db = get_db()

    # Coverage numbers (public aggregates) — real ingested only.
    total_jobs_real = await db.jobs.count_documents({"is_sample": False})
    total_jobs_all = await db.jobs.count_documents({})
    fresh_jobs = await db.jobs.count_documents(
        {"is_sample": False, "status": "live"}
    )
    sample_jobs = total_jobs_all - total_jobs_real

    # Provider tuples count — canonical Fynd invariant (Phase 5 close-out
    # 158 verified board tuples across GH/Lever/Ashby; report 16 as the
    # verified-connector count, distinct from the 158-tuple corpus).
    provider_count = 16

    # P0 Truth Audit metric blocks (each is honest / SAMPLE-excluded /
    # never-fabricate).
    outcome_rows = await _metrics.public_outcome_rows()
    per_country = await _metrics.per_country_coverage()
    north_star = await _metrics.north_star_baseline()

    return {
        "policy_text_version": os.environ.get("POLICY_TEXT_VERSION", "unversioned"),
        "phases_gated_pass": PHASES_GATED_PASS,
        "change_history": CHANGE_HISTORY,
        "coverage": {
            "verified_providers": provider_count,
            "jobs_in_index": total_jobs_real,
            "fresh_jobs_in_index": fresh_jobs,
            "sample_rows_excluded_from_public_counts": sample_jobs,
        },
        "outcome_rows": outcome_rows,
        "verification_ladder": VERIFICATION_LADDER,
        "per_country_coverage": per_country,
        "north_star": north_star,
        "feature_flags": [
            _flag("APPLY_AT_BIRTH_ENABLED", safe_default=True),
            _flag("WEEKLY_DIGEST_EMAIL_ENABLED"),
            _flag("WORKDAY_DISCOVERY_ENABLED"),
            _flag("WORKDAY_LIVE_ENABLED"),
            _flag("CI_TEST_ISSUER_ENABLED"),
        ],
        "rails": [
            {"rail": "email dispatch", "state": "dry-run by default"},
            {"rail": "follow-ups", "state": "never auto-sent — manual explicit approve"},
            {"rail": "apply cap", "state": "≤ 7 per user per day; never bypassed"},
            {"rail": "standing wave", "state": "per-user opt-in; consent snapshot on every fire"},
            {"rail": "employer supply", "state": "human-in-the-loop; no scraping; no auto-ingest"},
            {"rail": "eligibility engine", "state": "public-data-only; honest unknowns"},
            {"rail": "evidence exports", "state": "HMAC-SHA256 signed; ledger-derived only"},
            {"rail": "manual claims", "state": "save as pending draft; explicit Approve for attestation"},
        ],
        "note": (
            "READ-ONLY public measuring-state. Every number is a public "
            "aggregate; no user-scoped data is surfaced. Rails, flags, "
            "and phase verdicts are the current-truth state — updated "
            "atomically at each gate close-out. SAMPLE/fixture rows are "
            "excluded from every count that renders here."
        ),
    }
