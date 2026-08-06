"""Static seed data. Idempotent — the seeder uses upserts keyed by unique fields."""

# ---------------------------------------------------------------------------
# Taxonomy: exactly 13 role families as specified in the Phase 1 brief.
# ---------------------------------------------------------------------------
TAXONOMY: list[dict] = [
    {"family": "vehicle systems", "synonyms": [
        "vehicle systems engineer", "vehicle integration engineer", "platform systems engineer"
    ]},
    {"family": "battery systems/test", "synonyms": [
        "battery systems engineer", "battery test engineer", "cell testing engineer", "battery integration engineer"
    ]},
    {"family": "simulation (MIL/SIL/HIL)", "synonyms": [
        "MIL engineer", "SIL engineer", "HIL engineer", "model-in-the-loop", "software-in-the-loop", "hardware-in-the-loop",
        "simulation engineer", "virtual validation engineer"
    ]},
    {"family": "controls", "synonyms": [
        "controls engineer", "control systems engineer", "model based controls engineer", "powertrain controls engineer"
    ]},
    {"family": "vehicle dynamics", "synonyms": [
        "vehicle dynamics engineer", "chassis controls engineer", "ride and handling engineer"
    ]},
    {"family": "thermal/energy", "synonyms": [
        "thermal systems engineer", "energy systems engineer", "HVAC engineer", "battery thermal engineer"
    ]},
    {"family": "mechanical design", "synonyms": [
        "mechanical design engineer", "mechanical engineer", "CAD engineer", "packaging engineer"
    ]},
    {"family": "test engineer", "synonyms": [
        "test engineer", "validation engineer", "vehicle test engineer", "reliability test engineer"
    ]},
    {"family": "robotics", "synonyms": [
        "robotics engineer", "autonomy engineer", "perception engineer", "motion planning engineer"
    ]},
    {"family": "applications engineer", "synonyms": [
        "applications engineer", "field applications engineer", "solutions engineer"
    ]},
    {"family": "systems engineer", "synonyms": [
        "systems engineer", "MBSE engineer", "requirements engineer"
    ]},
    {"family": "manufacturing/process", "synonyms": [
        "manufacturing engineer", "process engineer", "production engineer", "industrialization engineer"
    ]},
    {"family": "equipment engineer", "synonyms": [
        "equipment engineer", "tooling engineer", "fab equipment engineer", "process equipment engineer"
    ]},
]

# ---------------------------------------------------------------------------
# 25 real employers. NO invented jobs are attached to these — only static metadata.
# ---------------------------------------------------------------------------
COMPANIES: list[dict] = [
    {"domain": "lucidmotors.com",       "name": "Lucid Motors",              "ats_type": "greenhouse"},
    {"domain": "tsmc.com",              "name": "TSMC Arizona",               "ats_type": "workday"},
    {"domain": "amkor.com",             "name": "Amkor Technology",           "ats_type": "workday"},
    {"domain": "lgensol.com",           "name": "LG Energy Solution",         "ats_type": "workday"},
    {"domain": "waymo.com",             "name": "Waymo",                      "ats_type": "greenhouse"},
    {"domain": "tesla.com",             "name": "Tesla",                      "ats_type": "custom"},
    {"domain": "rivian.com",            "name": "Rivian",                     "ats_type": "workday"},
    {"domain": "zoox.com",              "name": "Zoox",                       "ats_type": "greenhouse"},
    {"domain": "ford.com",              "name": "Ford Motor Company",         "ats_type": "workday"},
    {"domain": "gm.com",                "name": "General Motors",             "ats_type": "workday"},
    {"domain": "cummins.com",           "name": "Cummins",                    "ats_type": "workday"},
    {"domain": "bosch.com",             "name": "Bosch",                      "ats_type": "successfactors"},
    {"domain": "mathworks.com",         "name": "MathWorks",                  "ats_type": "custom"},
    {"domain": "appliedintuition.com",  "name": "Applied Intuition",          "ats_type": "greenhouse"},
    {"domain": "aptiv.com",             "name": "Aptiv",                      "ats_type": "workday"},
    {"domain": "magna.com",             "name": "Magna International",        "ats_type": "workday"},
    {"domain": "borgwarner.com",        "name": "BorgWarner",                 "ats_type": "successfactors"},
    {"domain": "avl.com",               "name": "AVL",                        "ats_type": "successfactors"},
    {"domain": "dspace.com",            "name": "dSPACE",                     "ats_type": "custom"},
    {"domain": "etas.com",              "name": "ETAS",                       "ats_type": "successfactors"},
    {"domain": "gtisoft.com",           "name": "Gamma Technologies",         "ats_type": "custom"},
    {"domain": "altair.com",            "name": "Altair",                     "ats_type": "workday"},
    {"domain": "ansys.com",             "name": "Ansys",                      "ats_type": "workday"},
    {"domain": "intel.com",             "name": "Intel",                      "ats_type": "workday"},
    {"domain": "onsemi.com",            "name": "onsemi",                     "ats_type": "workday"},
]

# ---------------------------------------------------------------------------
# 15 SAMPLE jobs. ALL attributed to "SampleCo (demo)", is_sample=true.
# Phase 2: each carries eligibility_requirements to feed the gate engine.
# Distribution: 2 jobs require US-person (ITAR), 4 jobs offer NO sponsorship.
# ---------------------------------------------------------------------------
SAMPLE_COMPANY = {"domain": "sampleco.demo", "name": "SampleCo (demo)", "ats_type": "sample"}

# Phase 1 §iv fix (2026-08-06) — SECOND sample employer with response-outcome
# history so `sort=speed` can differentially rank data-bearing employers first.
# Clearly labeled as fixture/SAMPLE; never a real employer.
SAMPLE_COMPANY_2 = {"domain": "responsivedemo.demo", "name": "ResponsiveDemo (fixture)", "ats_type": "sample"}

# Extra SAMPLE jobs attributed to SAMPLE_COMPANY_2. These are FIXTURE-only —
# their purpose is to give `sort=speed` a data-bearing employer so the ranking
# is observably different from the no-data bucket.
SAMPLE_JOBS_RESPONSIVE: list[dict] = [
    # Passes gates for fixture-ead (Phoenix, sponsors, comp >= 90k, offers_sponsorship).
    {"title": "Vehicle Systems Engineer — R", "family": "vehicle systems",
      "geo": "Phoenix, AZ", "comp": "$118k-$150k", "apply_method": "internal",
      "eligibility": {"requires_us_person": False, "offers_sponsorship": True},
      "jd": "Responsive fixture role — Own vehicle-level requirements. This role is a fixture demo for the sort=speed data-bearing employer."},
    # Remote US — passes for fixture-ead too.
    {"title": "HIL Simulation Engineer — R", "family": "simulation (MIL/SIL/HIL)",
      "geo": "Remote (US)", "comp": "$115k-$150k", "apply_method": "ats-workday",
      "eligibility": {"requires_us_person": False, "offers_sponsorship": True},
      "jd": "Responsive fixture role — HIL bench for a fixture demo. This role is fixture-only, used to visualize sort=speed."},
]

SAMPLE_JOBS: list[dict] = [
    # 1 — PASS for fixture-ead (Phoenix, AZ; offers_sponsorship True; comp ≥ 90k)
    {"title": "Vehicle Systems Engineer", "family": "vehicle systems",
     "geo": "Phoenix, AZ", "comp": "$115k-$150k", "apply_method": "internal",
     "eligibility": {"requires_us_person": False, "offers_sponsorship": True},
     "jd": "Own vehicle-level requirements decomposition for a new EV platform. Interface with subsystem owners for propulsion, thermal, and HV. MBSE workflow."},
    # 2 — FAIL sponsorship (offers_sponsorship=False). Location matches fixture so it fails on ONE cause only.
    {"title": "Battery Test Engineer", "family": "battery systems/test",
     "geo": "Phoenix, AZ", "comp": "$105k-$140k", "apply_method": "external",
     "eligibility": {"requires_us_person": False, "offers_sponsorship": False},
     "jd": "Design and execute cell-level and module-level test plans. Own bench safety and DAQ instrumentation. Reduce test cycle time. Visa sponsorship not available."},
    # 3 — PASS (Remote US)
    {"title": "HIL Simulation Engineer", "family": "simulation (MIL/SIL/HIL)",
     "geo": "Remote (US)", "comp": "$110k-$150k", "apply_method": "ats-workday",
     "eligibility": {"requires_us_person": False, "offers_sponsorship": True},
     "jd": "Build and maintain HIL benches for powertrain and chassis controls. Author plant models in Simulink. Own signal fidelity budgets."},
    # 4 — PASS (Phoenix, AZ; years_min moderated in REQ_BY_TITLE below)
    {"title": "Powertrain Controls Engineer", "family": "controls",
     "geo": "Phoenix, AZ", "comp": "$120k-$155k", "apply_method": "internal",
     "eligibility": {"requires_us_person": False, "offers_sponsorship": True},
     "jd": "Develop model-based controls for e-axle torque management. Deliver production-quality Simulink models and calibrations."},
    # 5 — PASS (Phoenix, AZ)
    {"title": "Vehicle Dynamics Engineer", "family": "vehicle dynamics",
     "geo": "Phoenix, AZ", "comp": "$115k-$145k", "apply_method": "external",
     "eligibility": {"requires_us_person": False, "offers_sponsorship": True},
     "jd": "Own ride and handling objective/subjective targets. Correlate CarMaker/CarSim models to physical proving-ground data."},
    # 6 — FAIL sponsorship (offers_sponsorship=False, location matches)
    {"title": "Battery Thermal Engineer", "family": "thermal/energy",
     "geo": "Remote (US)", "comp": "$120k-$160k", "apply_method": "ats-greenhouse",
     "eligibility": {"requires_us_person": False, "offers_sponsorship": False},
     "jd": "Design pack-level thermal management. 1D + 3D correlation. Own coolant flow and cell temperature targets under fast-charge. Sponsorship not offered."},
    # 7 — PASS (Phoenix, AZ; $95k ≥ $90k)
    {"title": "Mechanical Design Engineer", "family": "mechanical design",
     "geo": "Phoenix, AZ", "comp": "$95k-$130k", "apply_method": "external",
     "eligibility": {"requires_us_person": False, "offers_sponsorship": True},
     "jd": "Detail-design brackets, mounts, and enclosures for a battery pack. GD&T fluency. Own DFM reviews with suppliers."},
    # 8 — FAIL sponsorship (location matches so only one fail cause)
    {"title": "Vehicle Test Engineer", "family": "test engineer",
     "geo": "Phoenix, AZ", "comp": "$100k-$135k", "apply_method": "internal",
     "eligibility": {"requires_us_person": False, "offers_sponsorship": False},
     "jd": "Plan and execute proving-ground validation cycles. Author test plans, run DAQ, deliver crisp reports. Visa sponsorship not offered."},
    # 9 — FAIL ITAR (requires_us_person=True; location matches so only ONE fail cause)
    {"title": "Autonomy Systems Engineer", "family": "robotics",
     "geo": "Remote (US)", "comp": "$150k-$210k", "apply_method": "ats-greenhouse",
     "eligibility": {"requires_us_person": True, "offers_sponsorship": True, "notes": "US-person requirement per export-control obligations."},
     "jd": "Own end-to-end autonomy stack integration for a driverless platform. Perception <-> planning integration and safety case authoring. US-person status required per export controls."},
    # 10 — PASS (Remote US)
    {"title": "Applications Engineer - Simulation Tools", "family": "applications engineer",
     "geo": "Remote (US)", "comp": "$115k-$145k", "apply_method": "ats-workday",
     "eligibility": {"requires_us_person": False, "offers_sponsorship": True},
     "jd": "Support OEM customers deploying MIL/SIL/HIL toolchains. Build reference workflows. Author technical enablement content."},
    # 11 — PASS (Phoenix, AZ)
    {"title": "Model-Based Systems Engineer", "family": "systems engineer",
     "geo": "Phoenix, AZ", "comp": "$120k-$155k", "apply_method": "external",
     "eligibility": {"requires_us_person": False, "offers_sponsorship": True},
     "jd": "Author SysML models for vehicle-level architectures. Own requirements traceability from stakeholder needs to test verification."},
    # 12 — FAIL sponsorship (location matches)
    {"title": "Manufacturing Process Engineer", "family": "manufacturing/process",
     "geo": "Phoenix, AZ", "comp": "$95k-$125k", "apply_method": "ats-workday",
     "eligibility": {"requires_us_person": False, "offers_sponsorship": False},
     "jd": "Own line-side process for a new battery module assembly cell. Cycle-time analysis, PFMEA ownership, kaizen leadership. Sponsorship not available."},
    # 13 — FAIL ITAR (location matches so ONLY ITAR fires)
    {"title": "Fab Equipment Engineer", "family": "equipment engineer",
     "geo": "Phoenix, AZ", "comp": "$105k-$140k", "apply_method": "external",
     "eligibility": {"requires_us_person": True, "offers_sponsorship": True, "notes": "US-person requirement per export-control obligations for advanced fab tooling."},
     "jd": "Own uptime, yield, and MTBF for a critical fab-line tool. Partner with vendors on preventive-maintenance windows. US-person status required."},
    # 14 — PASS (Remote US)
    {"title": "SIL Software Engineer", "family": "simulation (MIL/SIL/HIL)",
     "geo": "Remote (US)", "comp": "$120k-$155k", "apply_method": "ats-workday",
     "eligibility": {"requires_us_person": False, "offers_sponsorship": True},
     "jd": "Stand up SIL frameworks for ADAS software. Automate test-case authoring. Own signal-fidelity trade studies."},
    # 15 — PASS (Phoenix, AZ)
    {"title": "EV Systems Engineer", "family": "vehicle systems",
     "geo": "Phoenix, AZ", "comp": "$125k-$160k", "apply_method": "ats-greenhouse",
     "eligibility": {"requires_us_person": False, "offers_sponsorship": True},
     "jd": "Own cross-subsystem requirements for a new BEV. Coordinate propulsion, HV distribution, and thermal targets."},
    # 16 — Phase 3 note-branch coverage: PhD REQUIRED + 8+ yrs REQUIRED. Fixture
    # user has MS + ~1yr, so both notes must fire on this job — the job stays
    # PASSING with two visible NOTES.
    {"title": "Principal Vehicle Autonomy Researcher", "family": "research",
     "geo": "Phoenix, AZ", "comp": "$180k-$240k", "apply_method": "internal",
     "eligibility": {"requires_us_person": False, "offers_sponsorship": True},
     "jd": ("Own the research direction for a new vehicle-autonomy platform. "
            "Requirements: PhD in Robotics, EE, or a related field is required. "
            "Minimum 8 years of experience in autonomous systems, perception, or planning is required. "
            "You will publish, mentor senior engineers, and partner with the CTO on multi-year roadmaps.")},
]

# ---------------------------------------------------------------------------
# User Zero — real seed. DO NOT fabricate additional facts about this person.
# All claims start with user_approved=false, status="pending", verification level 0.
# ---------------------------------------------------------------------------
USER_ZERO = {
    "email": "ujjwal@opportunityos.dev",
    "password": "Passport!Test0",
    "name": "Ujjwal Singla",
}

USER_ZERO_CLAIMS = [
    {"type": "identity", "value": {"name": "Ujjwal Singla"}, "sensitivity": "normal"},
    {"type": "location", "value": {"city": "Phoenix", "state": "AZ", "country": "US"}, "sensitivity": "normal"},
    {"type": "work_auth", "value": {"status": "unspecified", "note": "Eligibility to be confirmed by candidate."}, "sensitivity": "sealed"},
    {"type": "education", "value": {
        "degree": "MS",
        "field": "Automotive / Systems Engineering (self-described)",
        "institution": None,
        "expected_graduation": "2026-08",
    }, "sensitivity": "normal"},
    {"type": "project", "value": {
        "title": "EV battery simulation - range improvement",
        "summary": "Modeled EV battery/energy chain and drove an 80 km range improvement (modeled).",
        "tools": ["MATLAB", "Simulink"],
        "metric": {"name": "range_improvement_km", "value": 80, "type": "modeled"},
    }, "sensitivity": "normal"},
    {"type": "project", "value": {
        "title": "Asteroid rover design - NASA-partnered mission",
        "summary": "Contributed to the design of an asteroid rover for a NASA-partnered mission.",
    }, "sensitivity": "normal"},
    {"type": "employment", "value": {
        "role": "Independent CAD Consultant",
        "client": "withheld",
        "client_context": "publicly traded robotics company",
        "engagement_count": 4,
        "note": "Four discrete CAD consulting engagements. Client name withheld pending release.",
    }, "sensitivity": "normal"},
]

USER_ZERO_SKILLS = ["MATLAB", "Simulink", "SolidWorks", "ANSYS", "embedded systems", "mechanical design", "robotics", "EV systems"]

ADMIN_USER = {
    "email": "admin@opportunityos.dev",
    "password": "Admin!Console1",
    "name": "Fynd Admin",
    "role": "admin",
}

SUPPORT_USER = {
    "email": "support@opportunityos.dev",
    "password": "Support!Console1",
    "name": "Fynd Support",
    "role": "support",
}

FEATURE_FLAGS = [
    {"name": "feed_enabled", "enabled": True, "description": "Gates the /feed route + jobs feed."},
    {"name": "ai_generation_enabled", "enabled": False, "description": "Gates Phase 4 tailoring."},
    {"name": "application_tracker_enabled", "enabled": False, "description": "Gates Phase 5 tracker."},
    {"name": "billing_enabled", "enabled": False, "description": "Gates Phase 6 billing UI."},
]

# ---------------------------------------------------------------------------
# FIXTURE user — deterministic re-baseline every startup (Founder Fix #1).
# All rows keyed to this email are RESET on each seeder run so testing agents get
# a canonical acceptance-check-B state:
#   passport activated, eligibility=ead_opt, prefs Phoenix+Remote+$90k floor,
#   claims MS + 1 employment (3.5yrs) + skills MATLAB/Simulink/SolidWorks,
#   ZERO applications / hidden_jobs / match_scores / usage_meters.
# ---------------------------------------------------------------------------
FIXTURE_USER = {
    "email": "fixture-ead@opportunityos.dev",
    "password": "Fixture!Test1",
    "name": "Test Candidate (FIXTURE — automated tests only)",
}

FIXTURE_EMPLOYMENT_START = "2020-08"  # ~3.5 years by Feb 2026
FIXTURE_EMPLOYMENT_END = None  # Present

FIXTURE_ELIGIBILITY = {
    "status": "ead_opt",
    "dates": {"opt_end": "2027-12-31", "earliest_start": "2026-03-01"},
    "notes": "Synthetic fixture for automated testing. Not a real candidate.",
}

FIXTURE_PREFERENCES = {
    "role_families": ["vehicle systems", "simulation (MIL/SIL/HIL)", "controls", "vehicle dynamics",
                       "mechanical design", "applications engineer", "systems engineer"],
    "locations": ["Phoenix, AZ", "Remote (US)"],
    "remote_ok": True,
    "salary_floor_usd": 90000,
    "employer_include": [],
    "employer_exclude": [],
    "screener_answers": {},
    "search_intensity": "medium",
}

FIXTURE_CLAIMS = [
    {"type": "identity",   "value": {"name": "Test Candidate FIXTURE"}, "sensitivity": "normal"},
    {"type": "contact",    "value": {"email": "fixture-ead@opportunityos.dev"}, "sensitivity": "normal"},
    {"type": "location",   "value": {"city": "Phoenix", "state": "AZ", "country": "US"}, "sensitivity": "normal"},
    {"type": "education",  "value": {"institution": "Test University", "degree": "MS", "field": "Mechanical Engineering", "start": "2018-08", "end": "2020-05"}, "sensitivity": "normal"},
    {"type": "employment", "value": {"company": "Fixture Motors", "role": "Systems Engineer", "start": FIXTURE_EMPLOYMENT_START, "end": None, "summary": "Synthetic fixture experience."}, "sensitivity": "normal"},
]
FIXTURE_SKILLS = ["MATLAB", "Simulink", "SolidWorks", "MBSE", "requirements", "systems"]
