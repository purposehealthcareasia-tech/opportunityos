"""Credential-to-Income catalog (Phase 3 Founder Brief — actionable low-barrier
credentials that unlock hourly earning fast in Arizona / the U.S.).

Static, deterministic, offline. No network. Each row is:
  * label            — short credential name shown on the card
  * kind             — 'certification' | 'license' | 'permit' | 'training'
  * mandatory        — bool; True for statutorily-required licenses (mirrors gate_engine)
  * typical_hourly   — {"low": $/hr, "high": $/hr, "median": $/hr}
  * time_to_credential — {"weeks_low": N, "weeks_high": N}
  * approx_cost_usd  — {"low": $, "high": $}
  * suggested_next   — 1-2 places to start (official state URL or nationally recognized body)
  * notes            — plain-English caveats

These numbers are indicative ranges pulled from public state licensing / BLS data.
NEVER surfaced as guaranteed earnings. UI must render them as "typical" ranges.
"""
from __future__ import annotations

CATALOG: list[dict] = [
    {
        "id": "cdl-class-a",
        "label": "CDL Class A — Commercial Driver's License",
        "kind": "license",
        "mandatory": True,
        "typical_hourly": {"low": 22.0, "median": 26.0, "high": 32.0},
        "time_to_credential": {"weeks_low": 3, "weeks_high": 8},
        "approx_cost_usd": {"low": 3000, "high": 7000},
        "suggested_next": [
            {"label": "AZ MVD Commercial Driver License Manual",
             "url": "https://azdot.gov/mvd/services/driver-services/commercial-driver-license"},
            {"label": "FMCSA CDL Registry (nationally-recognized training providers)",
             "url": "https://tpr.fmcsa.dot.gov/"},
        ],
        "notes": "Requires DOT medical card + clean 3-yr driving record. Some carriers reimburse tuition.",
    },
    {
        "id": "cna",
        "label": "CNA — Certified Nursing Assistant (AZ)",
        "kind": "certification",
        "mandatory": True,
        "typical_hourly": {"low": 15.0, "median": 18.5, "high": 22.0},
        "time_to_credential": {"weeks_low": 4, "weeks_high": 12},
        "approx_cost_usd": {"low": 400, "high": 1800},
        "suggested_next": [
            {"label": "AZ State Board of Nursing — CNA info",
             "url": "https://www.azbn.gov/licenses-and-certifications/certified-nursing-assistants"},
        ],
        "notes": "Fingerprint clearance card required in AZ. Community colleges offer subsidized cohorts.",
    },
    {
        "id": "emt-basic",
        "label": "EMT-B — Emergency Medical Technician (AZ)",
        "kind": "certification",
        "mandatory": True,
        "typical_hourly": {"low": 17.0, "median": 20.0, "high": 24.0},
        "time_to_credential": {"weeks_low": 12, "weeks_high": 20},
        "approx_cost_usd": {"low": 900, "high": 2200},
        "suggested_next": [
            {"label": "AZ Dept of Health Services — EMS certification",
             "url": "https://www.azdhs.gov/preparedness/emergency-medical-services-trauma-system/index.php"},
        ],
        "notes": "National Registry (NREMT) exam required. Fingerprint clearance in AZ.",
    },
    {
        "id": "phlebotomy",
        "label": "Phlebotomy Technician (national cert.)",
        "kind": "certification",
        "mandatory": False,  # AZ doesn't mandate a state license but employers require cert.
        "typical_hourly": {"low": 15.5, "median": 18.0, "high": 22.0},
        "time_to_credential": {"weeks_low": 6, "weeks_high": 16},
        "approx_cost_usd": {"low": 600, "high": 2500},
        "suggested_next": [
            {"label": "ASCP Board of Certification — Phlebotomy",
             "url": "https://www.ascp.org/content/board-of-certification"},
        ],
        "notes": "Community-college phlebotomy programs often include clinical hours.",
    },
    {
        "id": "medical-assistant",
        "label": "Certified Medical Assistant (CCMA / RMA)",
        "kind": "certification",
        "mandatory": False,
        "typical_hourly": {"low": 16.0, "median": 19.0, "high": 24.0},
        "time_to_credential": {"weeks_low": 12, "weeks_high": 32},
        "approx_cost_usd": {"low": 1500, "high": 5000},
        "suggested_next": [
            {"label": "NHA CCMA credential",
             "url": "https://www.nhanow.com/certifications/clinical-medical-assistant"},
        ],
        "notes": "Not state-licensed in AZ but almost every clinic requires certification.",
    },
    {
        "id": "forklift-osha",
        "label": "Forklift Operator (OSHA-compliant training)",
        "kind": "training",
        "mandatory": False,  # Employer-provided under OSHA, but often required to be hired.
        "typical_hourly": {"low": 18.0, "median": 21.0, "high": 26.0},
        "time_to_credential": {"weeks_low": 1, "weeks_high": 2},
        "approx_cost_usd": {"low": 50, "high": 300},
        "suggested_next": [
            {"label": "OSHA Powered Industrial Trucks — 1910.178",
             "url": "https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.178"},
        ],
        "notes": "Many warehouses train on the clock — apply first, then get certified during onboarding.",
    },
    {
        "id": "food-handler-az",
        "label": "AZ Food Handler Card",
        "kind": "permit",
        "mandatory": True,  # State-mandated for food-service workers in AZ.
        "typical_hourly": {"low": 15.0, "median": 17.0, "high": 22.0},
        "time_to_credential": {"weeks_low": 0, "weeks_high": 1},
        "approx_cost_usd": {"low": 8, "high": 20},
        "suggested_next": [
            {"label": "AZ Health Services — Food-worker card requirements",
             "url": "https://www.azdhs.gov/preparedness/epidemiology-disease-control/food-safety-environmental-services/"},
        ],
        "notes": "Online, ~2 hours, same-day. Fastest credential-to-income unlock in AZ.",
    },
    {
        "id": "az-fingerprint-clearance",
        "label": "AZ Fingerprint Clearance Card (Level 1)",
        "kind": "permit",
        "mandatory": True,  # Prerequisite for many AZ jobs (schools, childcare, healthcare).
        "typical_hourly": {"low": 15.0, "median": 18.0, "high": 22.0},
        "time_to_credential": {"weeks_low": 2, "weeks_high": 8},
        "approx_cost_usd": {"low": 67, "high": 75},
        "suggested_next": [
            {"label": "AZ Dept of Public Safety — Fingerprint Clearance",
             "url": "https://www.azdps.gov/services/public/fingerprint"},
        ],
        "notes": "Required for K-12 aide, childcare, healthcare support. Apply once, use across employers.",
    },
    {
        "id": "guard-card-az",
        "label": "AZ Unarmed Security Guard License",
        "kind": "license",
        "mandatory": True,
        "typical_hourly": {"low": 15.5, "median": 18.0, "high": 22.0},
        "time_to_credential": {"weeks_low": 1, "weeks_high": 4},
        "approx_cost_usd": {"low": 60, "high": 200},
        "suggested_next": [
            {"label": "AZ DPS — Security Guard licensing",
             "url": "https://www.azdps.gov/services/public/security-guard"},
        ],
        "notes": "8-hour training + fingerprint clearance. Armed guard is a separate, longer path.",
    },
]


def get_catalog() -> list[dict]:
    """Return an immutable copy of the credential catalog."""
    return [dict(row) for row in CATALOG]


def by_id(cred_id: str) -> dict | None:
    for row in CATALOG:
        if row["id"] == cred_id:
            return dict(row)
    return None
