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

SAMPLE_JOBS: list[dict] = [
    {"title": "Vehicle Systems Engineer", "family": "vehicle systems",
     "geo": "Phoenix, AZ", "comp": "$115k-$150k", "apply_method": "internal",
     "eligibility": {"requires_us_person": False, "offers_sponsorship": True},
     "jd": "Own vehicle-level requirements decomposition for a new EV platform. Interface with subsystem owners for propulsion, thermal, and HV. MBSE workflow."},
    {"title": "Battery Test Engineer", "family": "battery systems/test",
     "geo": "San Jose, CA", "comp": "$105k-$140k", "apply_method": "external",
     "eligibility": {"requires_us_person": False, "offers_sponsorship": False},
     "jd": "Design and execute cell-level and module-level test plans. Own bench safety and DAQ instrumentation. Reduce test cycle time. Visa sponsorship not available."},
    {"title": "HIL Simulation Engineer", "family": "simulation (MIL/SIL/HIL)",
     "geo": "Detroit, MI", "comp": "$110k-$150k", "apply_method": "ats-workday",
     "eligibility": {"requires_us_person": False, "offers_sponsorship": True},
     "jd": "Build and maintain HIL benches for powertrain and chassis controls. Author plant models in Simulink. Own signal fidelity budgets."},
    {"title": "Powertrain Controls Engineer", "family": "controls",
     "geo": "Auburn Hills, MI", "comp": "$120k-$155k", "apply_method": "internal",
     "eligibility": {"requires_us_person": False, "offers_sponsorship": True},
     "jd": "Develop model-based controls for e-axle torque management. Deliver production-quality Simulink models and calibrations."},
    {"title": "Vehicle Dynamics Engineer", "family": "vehicle dynamics",
     "geo": "Plymouth, MI", "comp": "$115k-$145k", "apply_method": "external",
     "eligibility": {"requires_us_person": False, "offers_sponsorship": True},
     "jd": "Own ride and handling objective/subjective targets. Correlate CarMaker/CarSim models to physical proving-ground data."},
    {"title": "Battery Thermal Engineer", "family": "thermal/energy",
     "geo": "Fremont, CA", "comp": "$120k-$160k", "apply_method": "ats-greenhouse",
     "eligibility": {"requires_us_person": False, "offers_sponsorship": False},
     "jd": "Design pack-level thermal management. 1D + 3D correlation. Own coolant flow and cell temperature targets under fast-charge. Sponsorship not offered."},
    {"title": "Mechanical Design Engineer", "family": "mechanical design",
     "geo": "Tempe, AZ", "comp": "$95k-$130k", "apply_method": "external",
     "eligibility": {"requires_us_person": False, "offers_sponsorship": True},
     "jd": "Detail-design brackets, mounts, and enclosures for a battery pack. GD&T fluency. Own DFM reviews with suppliers."},
    {"title": "Vehicle Test Engineer", "family": "test engineer",
     "geo": "Yucca, AZ", "comp": "$100k-$135k", "apply_method": "internal",
     "eligibility": {"requires_us_person": False, "offers_sponsorship": False},
     "jd": "Plan and execute proving-ground validation cycles. Author test plans, run DAQ, deliver crisp reports. Visa sponsorship not offered."},
    {"title": "Autonomy Systems Engineer", "family": "robotics",
     "geo": "Mountain View, CA", "comp": "$150k-$210k", "apply_method": "ats-greenhouse",
     "eligibility": {"requires_us_person": True, "offers_sponsorship": True, "notes": "US-person requirement per export-control obligations."},
     "jd": "Own end-to-end autonomy stack integration for a driverless platform. Perception <-> planning integration and safety case authoring. US-person status required per export controls."},
    {"title": "Applications Engineer - Simulation Tools", "family": "applications engineer",
     "geo": "Remote (US)", "comp": "$115k-$145k", "apply_method": "ats-workday",
     "eligibility": {"requires_us_person": False, "offers_sponsorship": True},
     "jd": "Support OEM customers deploying MIL/SIL/HIL toolchains. Build reference workflows. Author technical enablement content."},
    {"title": "Model-Based Systems Engineer", "family": "systems engineer",
     "geo": "Torrance, CA", "comp": "$120k-$155k", "apply_method": "external",
     "eligibility": {"requires_us_person": False, "offers_sponsorship": True},
     "jd": "Author SysML models for vehicle-level architectures. Own requirements traceability from stakeholder needs to test verification."},
    {"title": "Manufacturing Process Engineer", "family": "manufacturing/process",
     "geo": "Normal, IL", "comp": "$95k-$125k", "apply_method": "ats-workday",
     "eligibility": {"requires_us_person": False, "offers_sponsorship": False},
     "jd": "Own line-side process for a new battery module assembly cell. Cycle-time analysis, PFMEA ownership, kaizen leadership. Sponsorship not available."},
    {"title": "Fab Equipment Engineer", "family": "equipment engineer",
     "geo": "Chandler, AZ", "comp": "$105k-$140k", "apply_method": "external",
     "eligibility": {"requires_us_person": True, "offers_sponsorship": True, "notes": "US-person requirement per export-control obligations for advanced fab tooling."},
     "jd": "Own uptime, yield, and MTBF for a critical fab-line tool. Partner with vendors on preventive-maintenance windows. US-person status required."},
    {"title": "SIL Software Engineer", "family": "simulation (MIL/SIL/HIL)",
     "geo": "Warren, MI", "comp": "$120k-$155k", "apply_method": "ats-workday",
     "eligibility": {"requires_us_person": False, "offers_sponsorship": True},
     "jd": "Stand up SIL frameworks for ADAS software. Automate test-case authoring. Own signal-fidelity trade studies."},
    {"title": "EV Systems Engineer", "family": "vehicle systems",
     "geo": "Newark, CA", "comp": "$125k-$160k", "apply_method": "ats-greenhouse",
     "eligibility": {"requires_us_person": False, "offers_sponsorship": True},
     "jd": "Own cross-subsystem requirements for a new BEV. Coordinate propulsion, HV distribution, and thermal targets."},
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
    "name": "OpportunityOS Admin",
    "role": "admin",
}

SUPPORT_USER = {
    "email": "support@opportunityos.dev",
    "password": "Support!Console1",
    "name": "OpportunityOS Support",
    "role": "support",
}

FEATURE_FLAGS = [
    {"key": "feed_enabled", "value": True},
    {"key": "ai_generation_enabled", "value": False},
    {"key": "application_tracker_enabled", "value": False},
    {"key": "billing_enabled", "value": False},
]
