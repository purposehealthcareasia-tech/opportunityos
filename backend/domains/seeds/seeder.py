import logging
import uuid
from core.db import get_db
from core.security import hash_password
from core.time_utils import utc_now
from core.policy import CONSENT_SCOPES, policy_version
from domains.seeds import data as seed_data

log = logging.getLogger("oppos.seeder")


async def _upsert_taxonomy() -> int:
    db = get_db()
    for row in seed_data.TAXONOMY:
        await db.taxonomy.update_one(
            {"family": row["family"]},
            {"$set": row, "$setOnInsert": {"id": str(uuid.uuid4())}},
            upsert=True,
        )
    return await db.taxonomy.count_documents({})


async def _upsert_companies() -> int:
    db = get_db()
    for row in [*seed_data.COMPANIES, seed_data.SAMPLE_COMPANY]:
        await db.companies.update_one(
            {"domain": row["domain"]},
            {
                "$set": {
                    "name": row["name"],
                    "ats_type": row["ats_type"],
                    "verified_domain": row["domain"] != "sampleco.demo",
                    "green_lane": False,
                },
                "$setOnInsert": {"id": str(uuid.uuid4()), "domain": row["domain"]},
            },
            upsert=True,
        )
    return await db.companies.count_documents({})


async def _upsert_sample_jobs() -> int:
    db = get_db()
    sample_company = await db.companies.find_one({"domain": "sampleco.demo"})
    company_id = sample_company["id"] if sample_company else None

    # Phase 3: per-job structured requirements. Keeps have/gap deterministic for tests
    # and lets the gate engine reason about experience_band + education_requirement.
    REQ_BY_TITLE = {
        "Vehicle Systems Engineer":              {"skills_required": ["mbse", "requirements", "systems"],          "degree_level": "BS", "years_min": 3},
        "Battery Test Engineer":                 {"skills_required": ["daq", "python", "battery test benches"],    "degree_level": "BS", "years_min": 2},
        "HIL Simulation Engineer":               {"skills_required": ["matlab", "simulink", "hil"],                "degree_level": "BS", "years_min": 4},
        "Powertrain Controls Engineer":          {"skills_required": ["matlab", "simulink", "controls"],           "degree_level": "MS", "years_min": 5},
        "Vehicle Dynamics Engineer":             {"skills_required": ["carmaker", "matlab", "vehicle dynamics"],   "degree_level": "BS", "years_min": 5},
        "Battery Thermal Engineer":              {"skills_required": ["ansys", "1d simulation", "thermal"],        "degree_level": "BS", "years_min": 4},
        "Mechanical Design Engineer":            {"skills_required": ["solidworks", "gd&t", "mechanical design"],  "degree_level": "BS", "years_min": 1},
        "Vehicle Test Engineer":                 {"skills_required": ["daq", "test plans", "proving ground"],      "degree_level": "BS", "years_min": 2},
        "Autonomy Systems Engineer":             {"skills_required": ["python", "ros", "autonomy"],                "degree_level": "MS", "years_min": 5},
        "Applications Engineer - Simulation Tools": {"skills_required": ["matlab", "simulink", "customer support"], "degree_level": "BS", "years_min": 3},
        "Model-Based Systems Engineer":          {"skills_required": ["sysml", "mbse", "requirements"],            "degree_level": "MS", "years_min": 4},
        "Manufacturing Process Engineer":        {"skills_required": ["pfmea", "kaizen", "manufacturing"],         "degree_level": "BS", "years_min": 2},
        "Fab Equipment Engineer":                {"skills_required": ["equipment", "yield", "mtbf"],               "degree_level": "BS", "years_min": 3},
        "SIL Software Engineer":                 {"skills_required": ["python", "sil", "adas"],                    "degree_level": "BS", "years_min": 3},
        "EV Systems Engineer":                   {"skills_required": ["ev systems", "hv distribution", "thermal"], "degree_level": "BS", "years_min": 3},
    }

    for idx, j in enumerate(seed_data.SAMPLE_JOBS, start=1):
        canonical_key = f"sampleco.demo::sample-{idx:02d}"
        req = dict(REQ_BY_TITLE.get(j["title"], {}))
        req.setdefault("skills_required", [])
        req.setdefault("licenses", [])
        await db.jobs.update_one(
            {"canonical_key": canonical_key},
            {
                "$set": {
                    "company_id": company_id,
                    "company_name": "SampleCo (demo)",
                    "company_domain": "sampleco.demo",
                    "source": "seed",
                    "origin_url": f"https://sampleco.demo/careers/sample-{idx:02d}",
                    "title": j["title"],
                    "taxonomy_family": j["family"],
                    "geo": j["geo"],
                    "comp": j["comp"],
                    "jd_text": j["jd"],
                    "apply_method": j["apply_method"],
                    "eligibility_requirements": j.get("eligibility", {}),
                    "requirements": req,
                    "first_seen": utc_now(),
                    "last_verified": utc_now(),
                    "status": "live",
                    "also_seen": [],
                    "is_sample": True,
                },
                "$setOnInsert": {"id": str(uuid.uuid4()), "canonical_key": canonical_key},
            },
            upsert=True,
        )
    return await db.jobs.count_documents({"is_sample": True})


async def _upsert_feature_flags() -> int:
    db = get_db()
    for f in seed_data.FEATURE_FLAGS:
        await db.feature_flags.update_one(
            {"key": f["key"]},
            {"$set": {"value": f["value"]}, "$setOnInsert": {"key": f["key"], "changed_by": "system"}},
            upsert=True,
        )
    return await db.feature_flags.count_documents({})


async def _ensure_user(email: str, password: str, name: str) -> str:
    """Return the user_id, creating the user if missing. Idempotent."""
    db = get_db()
    existing = await db.users.find_one({"email": email.lower()})
    if existing:
        return existing["id"]
    user_id = str(uuid.uuid4())
    await db.users.insert_one(
        {
            "id": user_id,
            "email": email.lower(),
            "password_hash": hash_password(password),
            "name": name,
            "passport_activated": False,
            "created_at": utc_now(),
        }
    )
    await db.audit_logs.insert_one(
        {
            "id": str(uuid.uuid4()),
            "actor": "system",
            "action": "seed.user_created",
            "object_ref": f"user:{user_id}",
            "ts": utc_now(),
            "meta": {"email": email.lower()},
        }
    )
    return user_id


async def _ensure_admin_role(user_id: str, role: str) -> None:
    db = get_db()
    await db.admin_users.update_one(
        {"user_id": user_id},
        {"$set": {"role": role}, "$setOnInsert": {"user_id": user_id}},
        upsert=True,
    )


async def _ensure_consent_seed(user_id: str) -> None:
    """Give User Zero a baseline consent record for process_career_data so tests can hit the passport endpoint.
    Others (discover_jobs / email_me etc.) stay OFF — explicit opt-in only.
    """
    db = get_db()
    for s in CONSENT_SCOPES:
        scope = s["scope"]
        already = await db.consent_records.find_one({"user_id": user_id, "scope": scope})
        if already:
            continue
        await db.consent_records.insert_one(
            {
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "scope": scope,
                "granted": s["required"],  # only required scopes granted on seed
                "policy_text_version": policy_version(),
                "ts": utc_now(),
                "actor": "system",
                "source": "seed",
            }
        )


async def _ensure_user_zero_claims(user_id: str, email: str) -> None:
    db = get_db()
    # Backfill: any claim rows missing a status get "pending" (Phase-1 rows created before
    # the status field existed). This keeps the append-only ledger intact and just adds
    # a discriminator so passport activation and claims listing know the row is a draft.
    await db.claims.update_many(
        {"user_id": user_id, "status": {"$exists": False}},
        {"$set": {"status": "pending"}},
    )
    # If claims already exist for this user, do not re-seed. Idempotent.
    if await db.claims.count_documents({"user_id": user_id}) > 0:
        return
    now = utc_now()
    base = {
        "user_id": user_id,
        "source": {"type": "user_provided", "note": "Seeded from User Zero baseline."},
        "evidence": [],
        "verification": {"level": 0, "note": "unverified"},
        "confidence": None,
        "user_approved": False,
        "status": "pending",
        "version": 1,
        "superseded_by": None,
        "created_at": now,
    }
    docs = []
    for c in seed_data.USER_ZERO_CLAIMS:
        docs.append({"id": str(uuid.uuid4()), "type": c["type"], "value": c["value"], "sensitivity": c["sensitivity"], **base})
    docs.append({
        "id": str(uuid.uuid4()),
        "type": "contact",
        "value": {"email": email.lower()},
        "sensitivity": "normal",
        **base,
    })
    for skill in seed_data.USER_ZERO_SKILLS:
        docs.append({
            "id": str(uuid.uuid4()),
            "type": "skill",
            "value": {"name": skill},
            "sensitivity": "normal",
            **base,
        })
    await db.claims.insert_many(docs)


async def run_seeds() -> dict:
    """Idempotent. Safe to call on every startup."""
    log.info("Running seeds…")
    counts = {
        "taxonomy": await _upsert_taxonomy(),
        "companies": await _upsert_companies(),
        "sample_jobs": await _upsert_sample_jobs(),
        "feature_flags": await _upsert_feature_flags(),
    }

    admin_id = await _ensure_user(seed_data.ADMIN_USER["email"], seed_data.ADMIN_USER["password"], seed_data.ADMIN_USER["name"])
    await _ensure_admin_role(admin_id, "admin")

    support_id = await _ensure_user(seed_data.SUPPORT_USER["email"], seed_data.SUPPORT_USER["password"], seed_data.SUPPORT_USER["name"])
    await _ensure_admin_role(support_id, "support")

    uz_id = await _ensure_user(seed_data.USER_ZERO["email"], seed_data.USER_ZERO["password"], seed_data.USER_ZERO["name"])
    await _ensure_consent_seed(uz_id)
    await _ensure_user_zero_claims(uz_id, seed_data.USER_ZERO["email"])

    counts.update({"admin_users": 2, "user_zero_id": uz_id})
    log.info("Seed counts: %s", counts)
    return counts
