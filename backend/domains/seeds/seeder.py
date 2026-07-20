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
        "HIL Simulation Engineer":               {"skills_required": ["matlab", "simulink", "hil"],                "degree_level": "BS", "years_min": 3},
        "Powertrain Controls Engineer":          {"skills_required": ["matlab", "simulink", "controls"],           "degree_level": "MS", "years_min": 3},
        "Vehicle Dynamics Engineer":             {"skills_required": ["carmaker", "matlab", "vehicle dynamics"],   "degree_level": "BS", "years_min": 3},
        "Battery Thermal Engineer":              {"skills_required": ["ansys", "1d simulation", "thermal"],        "degree_level": "BS", "years_min": 4},
        "Mechanical Design Engineer":            {"skills_required": ["solidworks", "gd&t", "mechanical design"],  "degree_level": "BS", "years_min": 1},
        "Vehicle Test Engineer":                 {"skills_required": ["daq", "test plans", "proving ground"],      "degree_level": "BS", "years_min": 2},
        "Autonomy Systems Engineer":             {"skills_required": ["python", "ros", "autonomy"],                "degree_level": "MS", "years_min": 5},
        "Applications Engineer - Simulation Tools": {"skills_required": ["matlab", "simulink", "customer support"], "degree_level": "BS", "years_min": 3},
        "Model-Based Systems Engineer":          {"skills_required": ["sysml", "mbse", "requirements"],            "degree_level": "MS", "years_min": 3},
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


async def _one_time_user_zero_cleanup(user_id: str) -> None:
    """Founder Fix #3 — one-time cleanup of tester pollution on User Zero.

    Guarded by a `seed_migrations` marker so this runs exactly once. Removes:
      - preferences (test runs saved Austin+$120k floor)
      - eligibility_profiles (test runs set 'citizen')
      - applications, hidden_jobs, match_scores (leftover state)
      - usage_meters (test-driven counters)
      - documents + resume_versions (test-uploaded résumés)
    LEAVES intact: claims (approvals from tests are harmless), consent_records (append-only),
    audit_logs (append-only), users row itself.

    Passport_activated is recomputed by checking approved-claim requirements.
    """
    db = get_db()
    marker_key = "user_zero_cleanup_v3"
    already = await db.seed_migrations.find_one({"key": marker_key})
    if already:
        return
    to_wipe = [
        "preferences", "eligibility_profiles", "applications", "hidden_jobs",
        "match_scores", "usage_meters", "documents", "resume_versions",
        "score_feedback",
    ]
    counts = {}
    for coll in to_wipe:
        res = await db[coll].delete_many({"user_id": user_id})
        counts[coll] = res.deleted_count
    # Also purge any derived-import jobs User Zero created during prior test runs.
    res = await db.jobs.delete_many({"imported_by": user_id})
    counts["derived_jobs_imported_by_user_zero"] = res.deleted_count
    # Recompute passport_activated from approved claims
    has_identity = await db.claims.count_documents({
        "user_id": user_id, "type": "identity", "status": "approved",
    })
    has_edu_emp = await db.claims.count_documents({
        "user_id": user_id, "type": {"$in": ["education", "employment"]}, "status": "approved",
    })
    should_be_activated = bool(has_identity and has_edu_emp)
    await db.users.update_one({"id": user_id}, {"$set": {"passport_activated": should_be_activated}})
    await db.seed_migrations.insert_one({
        "key": marker_key,
        "ran_at": utc_now(),
        "user_id": user_id,
        "deleted": counts,
        "recomputed_passport_activated": should_be_activated,
    })
    await db.audit_logs.insert_one({
        "id": str(uuid.uuid4()),
        "actor": "system",
        "action": "seed.user_zero_cleanup_v3",
        "object_ref": f"user:{user_id}",
        "ts": utc_now(),
        "meta": {"deleted": counts, "passport_activated": should_be_activated},
    })
    log.info("User Zero one-time cleanup applied: %s", counts)


async def _rebase_fixture_user() -> str:
    """Founder Fix #1 — deterministic re-baseline of the FIXTURE test user on EVERY startup.

    Wipes every derivable state row for this user and re-seeds to the acceptance-check-B
    profile. Returns the user_id.
    """
    db = get_db()
    fx = seed_data.FIXTURE_USER
    email = fx["email"].lower()
    now = utc_now()
    # Ensure the user record exists (idempotent create).
    user_id = await _ensure_user(email, fx["password"], fx["name"])
    # Wipe all derivable state.
    to_wipe = [
        "preferences", "eligibility_profiles", "applications", "hidden_jobs",
        "match_scores", "usage_meters", "documents", "resume_versions",
        "score_feedback", "claims", "consent_records",
    ]
    for coll in to_wipe:
        await db[coll].delete_many({"user_id": user_id})
    # Grant all consents (required + optional discover_jobs/generate_materials/track_applications/email_me).
    for scope_row in CONSENT_SCOPES:
        await db.consent_records.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "scope": scope_row["scope"],
            "granted": True,
            "policy_text_version": policy_version(),
            "ts": now,
            "actor": "system:fixture",
            "source": "fixture_rebase",
        })
    # Seed claims — all APPROVED so the fixture user's passport is activatable.
    base_claim = {
        "user_id": user_id,
        "source": {"type": "user_provided", "note": "FIXTURE re-baseline. Synthetic data for automated tests only."},
        "evidence": [],
        "verification": {"level": 0, "note": "unverified"},
        "confidence": None,
        "user_approved": True,
        "status": "approved",
        "version": 1,
        "superseded_by": None,
        "created_at": now,
    }
    docs = []
    for c in seed_data.FIXTURE_CLAIMS:
        docs.append({"id": str(uuid.uuid4()), "type": c["type"], "value": c["value"], "sensitivity": c["sensitivity"], **base_claim})
    for skill in seed_data.FIXTURE_SKILLS:
        docs.append({"id": str(uuid.uuid4()), "type": "skill", "value": {"name": skill}, "sensitivity": "normal", **base_claim})
    if docs:
        await db.claims.insert_many(docs)
    # Seed preferences (version 1).
    await db.preferences.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "version": 1,
        "payload": seed_data.FIXTURE_PREFERENCES,
        "updated_at": now,
    })
    # Seed eligibility (version 1) — sealed by design.
    from services.gate_engine import derive_flags
    await db.eligibility_profiles.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "version": 1,
        "status": seed_data.FIXTURE_ELIGIBILITY["status"],
        "dates": seed_data.FIXTURE_ELIGIBILITY["dates"],
        "notes": seed_data.FIXTURE_ELIGIBILITY["notes"],
        "derived_flags": derive_flags(seed_data.FIXTURE_ELIGIBILITY["status"]),
        "sensitivity": "sealed",
        "updated_at": now,
    })
    # Activate passport.
    await db.users.update_one({"id": user_id}, {"$set": {"passport_activated": True}})
    # Audit row.
    await db.audit_logs.insert_one({
        "id": str(uuid.uuid4()),
        "actor": "system:fixture",
        "action": "seed.fixture_rebase",
        "object_ref": f"user:{user_id}",
        "ts": now,
        "meta": {"email": email},
    })
    log.info("FIXTURE user re-baselined: %s (%s)", email, user_id)
    return user_id


async def _cleanup_non_sample_test_jobs() -> int:
    """Founder Fix — remove ingest-created test pollution from prior runs.

    Rule: keep `is_sample=True` seeded jobs and keep user-imported `status='derived'` jobs.
    Anything else (test ingests via /api/internal/jobs/bulk during CI runs) is scrubbed on
    startup so the coverage-preview and feed acceptance numbers stay deterministic.
    """
    db = get_db()
    res = await db.jobs.delete_many({
        "$and": [
            {"$or": [{"is_sample": {"$exists": False}}, {"is_sample": False}]},
            {"$or": [{"status": {"$ne": "derived"}}, {"imported_by": {"$exists": False}}]},
        ]
    })
    if res.deleted_count:
        log.info("Purged %d non-sample non-derived test jobs", res.deleted_count)
    return res.deleted_count


async def run_seeds() -> dict:
    """Idempotent. Safe to call on every startup."""
    log.info("Running seeds…")
    counts = {
        "taxonomy": await _upsert_taxonomy(),
        "companies": await _upsert_companies(),
        "purged_test_jobs": await _cleanup_non_sample_test_jobs(),
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
    # One-time (marker-guarded) cleanup of tester pollution on User Zero.
    await _one_time_user_zero_cleanup(uz_id)

    # FIXTURE user — deterministic re-baseline on EVERY startup.
    fx_id = await _rebase_fixture_user()

    counts.update({"admin_users": 2, "user_zero_id": uz_id, "fixture_user_id": fx_id})
    log.info("Seed counts: %s", counts)
    return counts
