import logging
import os
import uuid
from core.config import settings
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
    for row in [*seed_data.COMPANIES, seed_data.SAMPLE_COMPANY, seed_data.SAMPLE_COMPANY_2]:
        await db.companies.update_one(
            {"domain": row["domain"]},
            {
                "$set": {
                    "name": row["name"],
                    "ats_type": row["ats_type"],
                    "verified_domain": row["domain"] not in ("sampleco.demo", "responsivedemo.demo"),
                    "green_lane": False,
                },
                "$setOnInsert": {"id": str(uuid.uuid4()), "domain": row["domain"]},
            },
            upsert=True,
        )
    return await db.companies.count_documents({})


async def _upsert_sample_jobs_responsive() -> int:
    """Phase 1 §iv fix (2026-08-06) — upsert SAMPLE jobs attributed to
    SAMPLE_COMPANY_2 (`responsivedemo.demo`). These exist so `sort=speed`
    has a data-bearing employer to rank above the no-data bucket.

    Kept minimal: 2 jobs, both PASS gates for `fixture-ead@` (Phoenix +
    Remote US, sponsors, comp inside band). Requirements shape mirrors
    `_upsert_sample_jobs` so the gate engine treats them the same.
    """
    db = get_db()
    company = await db.companies.find_one({"domain": "responsivedemo.demo"})
    company_id = company["id"] if company else None
    for idx, j in enumerate(seed_data.SAMPLE_JOBS_RESPONSIVE, start=1):
        canonical_key = f"responsivedemo.demo::sample-{idx:02d}"
        req = {
            "skills_required": ["matlab", "simulink", "systems"],
            "licenses": [], "degree_level": "BS", "years_min": 2,
        }
        screener_questions = [
            {"id": f"{canonical_key}#q-yoe", "kind": "normal",
              "category": "years_of_experience",
              "question_pattern": "years_of_experience:matlab",
              "text": "How many years of MATLAB experience?", "order_hint": 1},
            {"id": f"{canonical_key}#q-visa", "kind": "sensitive_visa",
              "category": "work_authorization",
              "question_pattern": "work_authorization_status",
              "text": "Are you authorized to work in the US? Sponsorship needed?", "order_hint": 2},
        ]
        await db.jobs.update_one(
            {"canonical_key": canonical_key},
            {
                "$set": {
                    "company_id": company_id,
                    "company_name": "ResponsiveDemo (fixture)",
                    "company_domain": "responsivedemo.demo",
                    "source": "seed",
                    "origin_url": f"https://responsivedemo.demo/careers/sample-{idx:02d}",
                    "title": j["title"],
                    "taxonomy_family": j["family"],
                    "geo": j["geo"],
                    "comp": j["comp"],
                    "jd_text": j["jd"],
                    "apply_method": j["apply_method"],
                    "eligibility_requirements": j.get("eligibility", {}),
                    "requirements": req,
                    "screener_questions": screener_questions,
                    "first_seen": utc_now(),
                    "last_verified": utc_now(),
                    "status": "live",
                    "also_seen": [],
                    "is_sample": True,
                    "lane": "career",
                    "distance_from_phoenix_mi": 0.0 if "Phoenix" in (j.get("geo") or "") else None,
                },
                "$setOnInsert": {"id": str(uuid.uuid4()), "canonical_key": canonical_key},
            },
            upsert=True,
        )
    return await db.jobs.count_documents({"company_domain": "responsivedemo.demo"})


async def _seed_fixture_speed_history(user_id: str, now) -> int:
    """Phase 1 §iv fix (2026-08-06) — seed FIXTURE-only application history +
    response outcomes against `SAMPLE_COMPANY_2` so `sort=speed` has a
    real median-days-to-response to rank on for `fixture-ead@`.

    Inserts three past applications submitted 45-90 days ago, each with
    a `response` outcome 3-5 days after submission. Median = 4d.

    Idempotent: wipes any prior `fixture=True` rows for this user against
    the responsive-demo employer before inserting.
    """
    from datetime import timedelta
    db = get_db()
    responsive_key_prefix = "responsivedemo.demo"
    # Wipe prior fixture rows for this user against this employer so this
    # is safe to re-run on every rebase.
    prior_apps = await db.applications.find(
        {"user_id": user_id, "fixture": True,
          "job_snapshot.company_domain": responsive_key_prefix},
        {"id": 1},
    ).to_list(length=None)
    if prior_apps:
        ids = [a["id"] for a in prior_apps]
        await db.applications.delete_many({"id": {"$in": ids}})
        await db.application_outcomes.delete_many({"application_id": {"$in": ids}})

    inserted = 0
    # 3 past applications with response outcomes @ known deltas so
    # median_days_to_response = 4.0 (middle value).
    entries = [
        # (days_ago_submitted, days_delta_to_response)
        (75, 3.0),
        (60, 4.0),
        (45, 5.0),
    ]
    for i, (submit_ago, delta_days) in enumerate(entries, start=1):
        submitted_at = now - timedelta(days=submit_ago)
        responded_at = submitted_at + timedelta(days=delta_days)
        app_id = str(uuid.uuid4())
        await db.applications.insert_one({
            "id": app_id,
            "user_id": user_id,
            "job_id": f"fixture-responsive-{i}",
            "state": "submitted",
            # NOTE: omit `company_id` so `_load_application_meta` falls back
            # to `canonical_key.split("::")[0]` == "responsivedemo.demo" —
            # the same key derived on the feed side. Without this the two
            # sides use different keys and speed-sort can't match rows.
            "job_snapshot": {
                "canonical_key": f"{responsive_key_prefix}::past-{i:02d}",
                "company_name": "ResponsiveDemo (fixture)",
                "company_domain": responsive_key_prefix,
                "title": f"Past Application {i}",
            },
            "submitted_at": submitted_at,
            "created_at": submitted_at,
            "fixture": True,
            "source": "fixture_rebase",
        })
        await db.application_outcomes.insert_one({
            "id": str(uuid.uuid4()),
            "application_id": app_id,
            "user_id": user_id,
            "kind": "response",
            "at": responded_at,
            "note": "fixture-seeded response outcome (demo data for sort=speed)",
            "fixture": True,
            "source": "fixture_rebase",
        })
        inserted += 1
    return inserted


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
        # Phase 3 note-branch coverage — real ATS jobs also parse now but this
        # fixture guarantees the "posting asks for X" note path is exercised
        # every run.
        "Principal Vehicle Autonomy Researcher": {"skills_required": ["autonomy", "perception", "planning"],       "degree_level": "PHD", "years_min": 8},
    }

    for idx, j in enumerate(seed_data.SAMPLE_JOBS, start=1):
        canonical_key = f"sampleco.demo::sample-{idx:02d}"
        req = dict(REQ_BY_TITLE.get(j["title"], {}))
        req.setdefault("skills_required", [])
        req.setdefault("licenses", [])
        # Phase 4 — deterministic screener set. Every SAMPLE job carries the SAME shape:
        #   2 normal questions, 1 visa (sensitive), 1 salary (sensitive), 1 demographic (static-only)
        # …so tests can assert the sensitive/demographic UX regardless of which sample they hit.
        screener_questions = [
            {
                "id": f"{canonical_key}#q-yoe-matlab",
                "kind": "normal",
                "category": "years_of_experience",
                "question_pattern": "years_of_experience:matlab",
                "text": "How many years of hands-on experience do you have with MATLAB or Simulink?",
                "order_hint": 1,
            },
            {
                "id": f"{canonical_key}#q-relocate",
                "kind": "normal",
                "category": "logistics",
                "question_pattern": "willing_to_relocate",
                "text": f"Are you willing to relocate to {j['geo']}? Please describe any timing constraints.",
                "order_hint": 2,
            },
            {
                "id": f"{canonical_key}#q-visa",
                "kind": "sensitive_visa",
                "category": "work_authorization",
                "question_pattern": "work_authorization_status",
                "text": "Are you legally authorized to work in the United States now, and will you require sponsorship for employment visa status in the future?",
                "order_hint": 3,
            },
            {
                "id": f"{canonical_key}#q-salary",
                "kind": "sensitive_salary",
                "category": "compensation",
                "question_pattern": "desired_base_salary_usd",
                "text": "What is your desired base salary range (annual, USD)?",
                "order_hint": 4,
            },
            {
                "id": f"{canonical_key}#q-eeo-block",
                "kind": "demographic",
                "category": "eeo",
                "question_pattern": "eeo_static_notice",
                "text": (
                    "Employers may ask about gender, race/ethnicity, veteran status, and disability "
                    "on their own forms. Fynd never stores, generates, or suggests answers "
                    "to these. Answer them directly on the employer's site if you choose to."
                ),
                "order_hint": 5,
            },
        ]
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
                    "screener_questions": screener_questions,
                    "first_seen": utc_now(),
                    "last_verified": utc_now(),
                    "status": "live",
                    "also_seen": [],
                    "is_sample": True,
                    # Phase 3 — SampleCo demos are Lane A (engineering). Also stamp
                    # distance so /feed?within_mi= filters can hit them.
                    "lane": "career",
                    "distance_from_phoenix_mi": 0.0 if "Phoenix" in (j.get("geo") or "") else None,
                },
                "$setOnInsert": {"id": str(uuid.uuid4()), "canonical_key": canonical_key},
            },
            upsert=True,
        )
    return await db.jobs.count_documents({"is_sample": True})


async def _upsert_feature_flags() -> int:
    db = get_db()
    now = utc_now()
    for f in seed_data.FEATURE_FLAGS:
        await db.feature_flags.update_one(
            {"name": f["name"]},
            {"$set": {"enabled": f["enabled"], "description": f.get("description", ""),
                       "updated_at": now},
             "$setOnInsert": {"name": f["name"], "created_at": now, "created_by": "system"}},
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
        "ai_generations", "screening_answers",
        # Phase 5 collections
        "authorization_scopes", "outcomes", "interviews",
        "manual_queue_items", "submission_receipts", "subscriptions",
        # Phase 3 (Founder Brief) — walk-ins + personas must reset with the fixture
        "walkins", "personas",
        # Phase 5.3/5.4 — outcome autopilot + self-healing per-user collections
        "application_outcomes", "budget_reallocations", "kill_list",
        "self_healing_events", "preflight_verdicts",
    ]
    for coll in to_wipe:
        await db[coll].delete_many({"user_id": user_id})
    # Also wipe any jobs the fixture user imported during earlier test runs (they carry
    # imported_by=fixture_user_id and would otherwise pollute the coverage-preview / feed
    # totals across pytest invocations).
    await db.jobs.delete_many({"imported_by": user_id})
    # And purge any orphan test-ingested jobs (is_sample=False AND status != 'derived')
    # so the acceptance geometry stays reproducible even when the whole suite runs.
    await _cleanup_non_sample_test_jobs()
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
    # Seed a base resume_version derived from approved claims (Phase 4 diff needs a base to
    # compare against).
    from services.llm import template_fallback_lines
    approved = [c for c in docs if c.get("status") == "approved"]
    base_lines = template_fallback_lines(approved)
    base_manifest = [
        {"line_id": str(uuid.uuid4()), "text": L["text"], "claim_ids": L["claim_ids"],
         "status": "accepted", "base_line_ref": None}
        for L in base_lines
    ]
    await db.resume_versions.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "application_id": None,
        "name": "base",
        "base": True,
        "render_manifest": {"lines": base_manifest},
        "s3_key": None,
        "sha256": None,
        "created_at": now,
        "updated_at": now,
    })
    # Phase 5 — seed the fixture user's subscription at plus (15 submits/day).
    # Founder brief: fixture-ead@ = plus; everyone else defaults to free.
    from domains.subscriptions import service as subs_svc
    await subs_svc.set_plan(user_id, "plus", actor="system:fixture")

    # Phase 6d — Application Credits — deterministic launch-ready balance.
    # Wipe the balance + ledger docs then materialize a fresh row with
    # 50 credits (starter default) so `fixture-ead@` demos the happy-path
    # Authorize & Launch flow. Companion doc `test_credentials.md` names
    # this fixture as the LAUNCH-READY demo user (Batch D UI).
    await db.application_credits_balance.delete_many({"user_id": user_id})
    await db.application_credits_ledger.delete_many({"user_id": user_id})
    await db.application_credits_balance.insert_one({
        "user_id": user_id, "plan": "starter", "balance": 50,
        "is_unlimited": False, "created_at": now, "updated_at": now,
    })
    await db.application_credits_ledger.insert_one({
        "id": str(uuid.uuid4()), "user_id": user_id,
        "direction": "grant", "amount": 50,
        "source": "fixture_rebase_launch_ready",
        "plan": "starter", "is_unlimited_flag": False, "ts": now,
    })
    # -----------------------------------------------------------------
    # Phase 5.3 / 5.4 UI-visibility seeds (Founder Directive 2026-07-28)
    # -----------------------------------------------------------------
    # Two fixture rows so the assisted-lane chip and the kill-list restore
    # CTA are visually verifiable on every future acceptance pass. Both
    # rows are clearly marked as fixture/SAMPLE data — never real
    # employers, never real submissions, and separate from the 9-passing
    # / 6-excluded gate geometry (feed reads jobs, not applications).
    await _seed_fixture_assisted_lane_row(user_id, now)
    await _seed_fixture_active_kill_list_row(user_id, now)
    await _seed_fixture_speed_history(user_id, now)
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


# --------------------------------------------------------------------- #
# Wider-prefs fixture user — Fynd Liquid tester-support (2026-08-04)
#
# Per founder directive item 5 in the Precision Protocol Amendment,
# the tester needs a truthful path to see one real Surprise Me draw.
# The primary fixture-ead@ user's EAD-with-sponsorship eligibility
# means most real Greenhouse/Lever/Ashby jobs fail the sponsorship
# gate as "unknown", so Surprise Me returns null (accurately). This
# second fixture user is us_citizen with wide-open role_families and
# no sponsorship requirement, so real jobs pass the hard gates and
# Surprise Me can draw a real outside-lane row.
#
# Rails preserved:
#   * Same seeding path as fixture-ead@ (deterministic re-baseline).
#   * Same production-mode guard prevents this from ever running in
#     prod (see rebase_all() at the top of this module).
#   * SAMPLE jobs are still excluded from Surprise Me (is_sample=False
#     filter is in the handler); the tester sees only REAL jobs.
# --------------------------------------------------------------------- #

FIXTURE_BROAD_EMAIL = "fixture-broad@opportunityos.dev"
# FIXTURE-ONLY password (preview / development only). Never runs in
# production because `run_seeds()` short-circuits when `PROD_MODE=true`
# (see lines 949-964 below) — this fixture user is not provisioned
# there. Parameterizable via env for local overrides; the literal
# below is the documented preview-invariant default so
# `/app/memory/test_credentials.md` and the seeder stay in sync
# without requiring an env var to be set in every preview pod.
FIXTURE_BROAD_PASSWORD = os.environ.get(
    "FIXTURE_BROAD_PASSWORD", "Fixture!Broad1"  # FIXTURE-ONLY default
)
FIXTURE_BROAD_NAME = "Fixture Broad-Prefs Tester"

# --- Phase 5g fixture: verified employer-member ---
# FIXTURE-ONLY (same prod-gate rails as FIXTURE_BROAD above). Provides
# the /api/v1/employer-dashboard/summary member-path with a real
# employer_memberships row so the 5g surface is independently testable
# without human-side employer onboarding flow. See test_credentials.md.
FIXTURE_EMPLOYER_MEMBER_EMAIL = "fixture-employer-member@opportunityos.dev"
FIXTURE_EMPLOYER_MEMBER_PASSWORD = os.environ.get(
    "FIXTURE_EMPLOYER_MEMBER_PASSWORD", "Fixture!Emp1"
)
FIXTURE_EMPLOYER_MEMBER_NAME = "Fixture Employer Member"
FIXTURE_EMPLOYER_CANONICAL_KEY = "fixture-employer-corp"

_BROAD_PREFERENCES = {
    # No role_families filter → every taxonomy_family is in play.
    "role_families": [],
    "locations": ["Anywhere (US)", "Remote (US)"],
    "remote_ok": True,
    "salary_floor_usd": 0,  # no floor
    "employer_include": [],
    "employer_exclude": [],
    "screener_answers": {},
    "search_intensity": "medium",
}

_BROAD_ELIGIBILITY = {
    "status": "us_citizen",
    "dates": {},
    "notes": "Synthetic fixture — wider-prefs tester profile so real Greenhouse/Lever/Ashby jobs pass the sponsorship gate and Surprise Me has a draw path.",
}

_BROAD_SKILLS = [
    "python", "product management", "javascript", "sql",
    "communication", "customer support", "operations",
    "marketing", "data analysis",
]


async def _rebase_fixture_broad_user() -> str:
    """Re-baseline the wider-prefs fixture user on every startup.

    Mirrors the shape of `_rebase_fixture_user` but with `us_citizen`
    eligibility and open role_families / no salary floor. Emits an
    audit row on completion; never touches employer origins.
    """
    db = get_db()
    now = utc_now()
    user_id = await _ensure_user(FIXTURE_BROAD_EMAIL, FIXTURE_BROAD_PASSWORD, FIXTURE_BROAD_NAME)

    to_wipe = [
        "preferences", "eligibility_profiles", "applications", "hidden_jobs",
        "match_scores", "usage_meters", "documents", "resume_versions",
        "score_feedback", "claims", "consent_records",
        "ai_generations", "screening_answers",
        "authorization_scopes", "outcomes", "interviews",
        "manual_queue_items", "submission_receipts", "subscriptions",
        "walkins", "personas",
        "application_outcomes", "budget_reallocations", "kill_list",
        "self_healing_events", "preflight_verdicts",
        "surprise_me_draws",
    ]
    for coll in to_wipe:
        await db[coll].delete_many({"user_id": user_id})

    # Grant every consent scope.
    for scope_row in CONSENT_SCOPES:
        await db.consent_records.insert_one({
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "scope": scope_row["scope"],
            "granted": True,
            "policy_text_version": policy_version(),
            "ts": now,
            "actor": "system:fixture-broad",
            "source": "fixture_broad_rebase",
        })

    # Approved contact + name claims + generalist skill set.
    base_claim = {
        "user_id": user_id,
        "source": {"type": "user_provided",
                     "note": "FIXTURE BROAD re-baseline. Synthetic data for automated tests only."},
        "evidence": [],
        "verification": {"level": 0, "note": "unverified"},
        "confidence": None,
        "user_approved": True,
        "status": "approved",
        "version": 1,
        "superseded_by": None,
        "created_at": now,
    }
    docs = [
        {"id": str(uuid.uuid4()), "type": "contact",
         "value": {"email": FIXTURE_BROAD_EMAIL},
         "sensitivity": "normal", **base_claim},
        {"id": str(uuid.uuid4()), "type": "name",
         "value": {"full_name": FIXTURE_BROAD_NAME,
                     "first_name": "Fixture", "last_name": "Broad-Prefs"},
         "sensitivity": "normal", **base_claim},
    ]
    for skill in _BROAD_SKILLS:
        docs.append({"id": str(uuid.uuid4()), "type": "skill",
                       "value": {"name": skill},
                       "sensitivity": "normal", **base_claim})
    if docs:
        await db.claims.insert_many(docs)

    await db.preferences.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "version": 1,
        "payload": _BROAD_PREFERENCES,
        "updated_at": now,
    })

    from services.gate_engine import derive_flags
    await db.eligibility_profiles.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "version": 1,
        "status": _BROAD_ELIGIBILITY["status"],
        "dates": _BROAD_ELIGIBILITY["dates"],
        "notes": _BROAD_ELIGIBILITY["notes"],
        "derived_flags": derive_flags(_BROAD_ELIGIBILITY["status"]),
        "sensitivity": "sealed",
        "updated_at": now,
    })

    await db.users.update_one({"id": user_id}, {"$set": {"passport_activated": True}})

    # Base resume_version so the passport can render.
    from services.llm import template_fallback_lines
    approved = [c for c in docs if c.get("status") == "approved"]
    base_lines = template_fallback_lines(approved)
    base_manifest = [
        {"line_id": str(uuid.uuid4()), "text": L["text"], "claim_ids": L["claim_ids"],
         "status": "accepted", "base_line_ref": None}
        for L in base_lines
    ]
    await db.resume_versions.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "application_id": None,
        "name": "base",
        "base": True,
        "render_manifest": {"lines": base_manifest},
        "s3_key": None,
        "sha256": None,
        "created_at": now,
        "updated_at": now,
    })

    from domains.subscriptions import service as subs_svc
    await subs_svc.set_plan(user_id, "plus", actor="system:fixture-broad")

    # Phase 6d — deterministic ZERO-credit balance for the 402 /
    # paused_no_credits demo. Wipe balance + ledger then materialize a
    # row at balance=0, is_unlimited=False. `test_credentials.md` names
    # this fixture as the ZERO-CREDIT demo user (Batch D UI).
    await db.application_credits_balance.delete_many({"user_id": user_id})
    await db.application_credits_ledger.delete_many({"user_id": user_id})
    await db.application_credits_balance.insert_one({
        "user_id": user_id, "plan": "starter", "balance": 0,
        "is_unlimited": False, "created_at": now, "updated_at": now,
    })
    await db.application_credits_ledger.insert_one({
        "id": str(uuid.uuid4()), "user_id": user_id,
        "direction": "grant", "amount": 0,
        "source": "fixture_broad_rebase_zero_credits",
        "plan": "starter", "is_unlimited_flag": False, "ts": now,
    })

    # Phase 6d Batch D — dispatchable application row so testers can
    # DIRECTLY exercise the HTTP 402 `paused_no_credits` branch on
    # `POST /api/v1/email-route/dispatch`. Preflight passes (approved
    # claims + base resume manifest already seeded above), credits are
    # 0, dispatch halts honestly. `test_credentials.md` documents the
    # discovery route via `GET /api/v1/applications`.
    await _seed_fixture_broad_dispatchable_app(user_id, now)

    await db.audit_logs.insert_one({
        "id": str(uuid.uuid4()),
        "actor": "system:fixture-broad",
        "action": "seed.fixture_broad_rebase",
        "object_ref": f"user:{user_id}",
        "ts": now,
        "meta": {"email": FIXTURE_BROAD_EMAIL,
                   "eligibility": _BROAD_ELIGIBILITY["status"]},
    })
    log.info("FIXTURE BROAD user re-baselined: %s (%s)",
              FIXTURE_BROAD_EMAIL, user_id)
    return user_id


async def _seed_fixture_broad_dispatchable_app(user_id: str, now) -> str | None:
    """Phase 6d Batch D — one shortlisted `applications` row on a SampleCo
    seed job so testers can DIRECTLY exercise the HTTP 402
    `paused_no_credits` branch on `POST /api/v1/email-route/dispatch`
    with `fixture-broad@` (which is deterministically re-baselined to
    balance=0).

    Rails: preflight passes because
      (a) fixture-broad has approved contact + name + skill claims,
      (b) the base resume manifest is seeded above (see
          `_rebase_fixture_broad_user` → `resume_versions`), and
      (c) the outbound body used in the tester's curl carries no
          numbers / years / sealed values and no signature (fixture-broad
          has no `identity`-type claim, so the signature branch is
          skipped in `_identity_check`).

    Discovery: the tester finds this row via
        GET /api/v1/applications
    then dispatches to it. Documented in `memory/test_credentials.md`.
    """
    db = get_db()
    sample_job = await db.jobs.find_one(
        {"is_sample": True}, {"_id": 0}, sort=[("_id", 1)],
    )
    if not sample_job:
        log.info("FIXTURE-BROAD dispatchable-app seed skipped: no SampleCo job found")
        return None
    from domains.applications.service import route_decision
    r = route_decision(sample_job)
    app_id = str(uuid.uuid4())
    doc = {
        "id": app_id,
        "user_id": user_id,
        "job_id": sample_job["id"],
        "company_id": sample_job.get("company_id"),
        "job_snapshot": {
            "title": sample_job.get("title"),
            "company_name": sample_job.get("company_name"),
            "canonical_key": sample_job.get("canonical_key"),
            "is_sample": True,
        },
        "state": "shortlisted",
        "route": r["route"],
        "route_rationale": r["rationale"],
        "materials": {},
        "authorization_id": None,
        "minutes_to_prepare": None,
        "fields_corrected": None,
        "created_at": now,
        "updated_at": now,
        # Fixture marker so operators can tell this apart from real applications.
        "fixture": True,
        "fixture_purpose": "phase6_batch_d_402_demo",
    }
    try:
        await db.applications.insert_one(doc)
    except Exception:
        log.warning("FIXTURE-BROAD dispatchable-app seed insert failed", exc_info=True)
        return None
    log.info("FIXTURE-BROAD 402-demo app seeded: %s (job=%s)", app_id, sample_job.get("id"))
    return app_id


async def _rebase_fixture_employer_member_user() -> str:
    """Phase 5g fixture — verified employer-member for the /5g member
    path. Rebaselines on every startup:
      * user account with FIXTURE_EMPLOYER_MEMBER_EMAIL
      * `employer_memberships` row `{user_id, employer_canonical_key,
        verified: True}` so `_resolve_employer` returns the key.
      * minimal `applications` seed (2 rows) + one response outcome
        so the summary endpoint returns non-null response_rate + a
        median_days_to_response value the tester can eyeball.

    FIXTURE-ONLY. Prod-gated by `run_seeds()` (line 949+).
    """
    db = get_db()
    user_id = await _ensure_user(
        FIXTURE_EMPLOYER_MEMBER_EMAIL,
        FIXTURE_EMPLOYER_MEMBER_PASSWORD,
        FIXTURE_EMPLOYER_MEMBER_NAME,
    )
    now = utc_now()
    # Idempotent membership row.
    await db.employer_memberships.update_one(
        {"user_id": user_id,
         "employer_canonical_key": FIXTURE_EMPLOYER_CANONICAL_KEY},
        {"$set": {
            "user_id": user_id,
            "employer_canonical_key": FIXTURE_EMPLOYER_CANONICAL_KEY,
            "verified": True,
            "verified_at": now,
            "role": "hiring_manager",
            "source": "seed:fixture-employer-member",
        }},
        upsert=True,
    )
    # Minimal apps + one response for a non-null dashboard readout.
    demo_apps = [
        {"id": f"fx-emp-app-{i}",
         "user_id": "fixture-emp-applicant-1",  # cross-user is fine — 5g surface aggregates by employer key, not user
         "employer_canonical_key": FIXTURE_EMPLOYER_CANONICAL_KEY,
         "score": 72 if i == 0 else 55,   # one passes gate (≥60), one below
         "created_at": now}
        for i in range(2)
    ]
    for app in demo_apps:
        await db.applications.update_one(
            {"id": app["id"]}, {"$set": app}, upsert=True,
        )
    # One responded event → drives response_rate + median_days_to_response.
    await db.application_outcomes.update_one(
        {"id": "fx-emp-outcome-1"},
        {"$set": {
            "id": "fx-emp-outcome-1",
            "application_id": "fx-emp-app-0",
            "employer_canonical_key": FIXTURE_EMPLOYER_CANONICAL_KEY,
            "event": "response_received",
            "lag_days": 4,
            "at": now,
            "source": "seed:fixture-employer-member",
        }},
        upsert=True,
    )
    log.info("FIXTURE employer-member re-baselined: %s (%s) → %s",
             FIXTURE_EMPLOYER_MEMBER_EMAIL, user_id,
             FIXTURE_EMPLOYER_CANONICAL_KEY)
    return user_id




# --------------------------------------------------------------------- #
# Phase 5.3 / 5.4 fixture UI-visibility seeds (Founder Directive)
# --------------------------------------------------------------------- #
# On EVERY backend restart these seed one demonstration row so the
# assisted-lane chip and the kill-list restore CTA render on the
# fixture user's account. Both rows are:
#   * clearly tagged as fixture/SAMPLE data,
#   * derived from SampleCo seed jobs (never a real employer),
#   * cleaned up by `to_wipe` on the next rebase (idempotent),
#   * separate from the 9-passing / 6-excluded feed geometry (feed
#     reads `jobs`, not `applications`).
# --------------------------------------------------------------------- #

_FIXTURE_ASSISTED_REASON = (
    "FIXTURE seed · form-map fill confidence dropped below threshold "
    "(low_confidence · sample) — sanctioned demo row so the assisted-lane "
    "chip is visible in preview."
)
_FIXTURE_KILL_LIST_EMPLOYER = "sampleco-demo-ghosts"
_FIXTURE_KILL_LIST_REASON = (
    "FIXTURE seed · 5 silence outcomes and zero viewed/response/interview "
    "signals in the last 21 days · sanctioned demo row so the restore CTA "
    "is exercisable in preview."
)


async def _seed_fixture_assisted_lane_row(user_id: str, now) -> str | None:
    """Create one applications row pinned to a SampleCo seed job and put
    it in `state=assisted` with a named `assisted_reason`. Uses a real
    SampleCo `is_sample=True` job so the app row's `job_snapshot.is_sample`
    is truthful and the UI badges it clearly."""
    db = get_db()
    sample_job = await db.jobs.find_one(
        {"is_sample": True}, {"_id": 0}, sort=[("_id", 1)],
    )
    if not sample_job:
        log.info("FIXTURE assisted-lane seed skipped: no SampleCo job found")
        return None
    from domains.applications.service import route_decision
    r = route_decision(sample_job)
    app_id = str(uuid.uuid4())
    doc = {
        "id": app_id,
        "user_id": user_id,
        "job_id": sample_job["id"],
        "company_id": sample_job.get("company_id"),
        "job_snapshot": {
            "title": sample_job.get("title"),
            "company_name": sample_job.get("company_name"),
            "canonical_key": sample_job.get("canonical_key"),
            "is_sample": True,
        },
        "state": "assisted",
        "assisted_reason": _FIXTURE_ASSISTED_REASON,
        "assisted_at": now,
        "route": r["route"],
        "route_rationale": r["rationale"],
        "materials": {},
        "authorization_id": None,
        "minutes_to_prepare": None,
        "fields_corrected": None,
        "created_at": now,
        "updated_at": now,
    }
    try:
        await db.applications.insert_one(doc)
    except Exception:
        # Do not break startup on any race — the seed is best-effort UI aid.
        log.warning("FIXTURE assisted-lane seed insert failed", exc_info=True)
        return None
    # Mirror the audit trail that self_healing.route_application_to_assisted
    # would have written, so the audit view is consistent.
    await db.self_healing_events.insert_one({
        "id": str(uuid.uuid4()),
        "kind": "app_routed_assisted",
        "source": "fixture_rebase",
        "context": {"application_id": app_id, "user_id": user_id,
                     "reason": _FIXTURE_ASSISTED_REASON,
                     "fixture": True},
        "at": now,
    })
    return app_id


async def _seed_fixture_active_kill_list_row(user_id: str, now) -> str:
    """Insert one ACTIVE kill-list row so the restore round-trip is
    visually exercisable on every future pass. `restored_at=None` keeps
    it under the `active` bucket of `GET /api/v1/outcomes/kill-list`."""
    db = get_db()
    row = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "employer": _FIXTURE_KILL_LIST_EMPLOYER,
        "reason": _FIXTURE_KILL_LIST_REASON,
        "created_at": now,
        "restored_at": None,
        "fixture": True,
    }
    await db.kill_list.insert_one(dict(row))
    return row["id"]


async def _cleanup_non_sample_test_jobs() -> int:
    """Founder Fix — remove ingest-created test pollution from prior runs.

    Rule: keep `is_sample=True` seeded jobs, keep user-imported `status='derived'`
    jobs, AND keep every discovery-ingested job (`source` starts with `discovery.`).
    Anything else (test ingests via /api/internal/jobs/bulk during CI runs) is
    scrubbed on startup so the coverage-preview and feed acceptance numbers stay
    deterministic.

    Fix 2026-07-27 (Phase 3 tester finding #2): earlier logic wiped the ~19,700
    real Greenhouse/Lever/Ashby jobs on every backend restart, forcing the
    scheduler to re-ingest them ~90s later. Feed appeared empty during that
    gap. `source: discovery.*` now bypasses the purge.
    """
    db = get_db()
    res = await db.jobs.delete_many({
        "$and": [
            {"$or": [{"is_sample": {"$exists": False}}, {"is_sample": False}]},
            {"$or": [{"status": {"$ne": "derived"}}, {"imported_by": {"$exists": False}}]},
            # NEVER purge discovery-ingested jobs.
            {"$or": [
                {"source": {"$exists": False}},
                {"source": {"$not": {"$regex": "^discovery\\."}}},
            ]},
        ]
    })
    if res.deleted_count:
        log.info("Purged %d non-sample non-derived non-discovery test jobs", res.deleted_count)
    return res.deleted_count


async def run_seeds() -> dict:
    """Idempotent. Safe to call on every startup.

    **Production safety guard** (2026-02-21 deployment readiness fix):
    When `PROD_MODE=true` the seeder ONLY provisions safe reference data
    (taxonomy + feature_flags). Demo data (SampleCo company, 15 sample jobs)
    and hardcoded-password fixture accounts (admin@ / support@ / ujjwal@ /
    fixture-ead@) are preview-only and MUST NEVER land in a production
    database. Real production admin bootstrap is a separate deploy-time
    concern (e.g. an admin-invite flow gated by an env-provisioned token),
    not a hardcoded password in `data.py`.
    """
    log.info("Running seeds… (PROD_MODE=%s)", settings.PROD_MODE)

    counts = {
        "taxonomy": await _upsert_taxonomy(),
        "feature_flags": await _upsert_feature_flags(),
    }

    if settings.PROD_MODE:
        log.info(
            "PROD_MODE=true — skipping demo companies, sample jobs, and all "
            "hardcoded-password fixture accounts. Reference data only."
        )
        counts.update({
            "companies": 0,
            "purged_test_jobs": 0,
            "sample_jobs": 0,
            "admin_users": 0,
            "user_zero_id": None,
            "fixture_user_id": None,
            "prod_mode_seed_skipped": True,
        })
        log.info("Seed counts: %s", counts)
        return counts

    counts["companies"] = await _upsert_companies()
    counts["purged_test_jobs"] = await _cleanup_non_sample_test_jobs()
    counts["sample_jobs"] = await _upsert_sample_jobs()
    counts["sample_jobs_responsive"] = await _upsert_sample_jobs_responsive()

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
    # Wider-prefs FIXTURE user for Surprise Me real-draw path (2026-08-04).
    fx_broad_id = await _rebase_fixture_broad_user()
    # Verified employer-member FIXTURE for 5g dashboard path (2026-08-09).
    await _rebase_fixture_employer_member_user()

    counts.update({"admin_users": 2, "user_zero_id": uz_id,
                     "fixture_user_id": fx_id,
                     "fixture_broad_user_id": fx_broad_id})
    log.info("Seed counts: %s", counts)
    return counts
