from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING
from core.config import settings

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(settings.MONGO_URL, uuidRepresentation="standard")
    return _client


def get_db() -> AsyncIOMotorDatabase:
    global _db
    if _db is None:
        _db = get_client()[settings.DB_NAME]
    return _db


async def ensure_indexes() -> None:
    db = get_db()
    await db.users.create_index("email", unique=True)
    await db.consent_records.create_index([("user_id", ASCENDING), ("scope", ASCENDING), ("ts", DESCENDING)])
    await db.authorization_scopes.create_index([("user_id", ASCENDING), ("kind", ASCENDING), ("target", ASCENDING)])
    await db.audit_logs.create_index([("actor", ASCENDING), ("ts", DESCENDING)])
    await db.audit_logs.create_index([("object_ref", ASCENDING), ("ts", DESCENDING)])
    await db.feature_flags.create_index("key", unique=True)
    await db.admin_users.create_index("user_id", unique=True)
    await db.documents.create_index("user_id")
    await db.documents.create_index("sha256")
    await db.documents.create_index("parse_status")
    await db.resume_versions.create_index([("user_id", ASCENDING), ("base", ASCENDING)])
    await db.preferences.create_index([("user_id", ASCENDING), ("version", DESCENDING)])
    await db.eligibility_profiles.create_index([("user_id", ASCENDING), ("version", DESCENDING)])
    await db.claims.create_index([("user_id", ASCENDING), ("type", ASCENDING)])
    await db.claims.create_index([("user_id", ASCENDING), ("status", ASCENDING)])
    await db.claims.create_index("superseded_by")
    await db.taxonomy.create_index("family", unique=True)
    await db.companies.create_index("domain", unique=True)
    await db.jobs.create_index("canonical_key", unique=True)
    await db.jobs.create_index("status")
    await db.jobs.create_index("taxonomy_family")
    await db.idempotency_records.create_index("key", unique=True)
    # 7-day TTL on idempotency records
    await db.idempotency_records.create_index("created_at", expireAfterSeconds=60 * 60 * 24 * 7)
    # Phase 3 collections
    await db.applications.create_index([("user_id", ASCENDING), ("job_id", ASCENDING)])
    # Partial unique: no more than one non-closed application per (user, job).
    # Mongo partial indexes don't support $ne, so enumerate allowed "open" states explicitly.
    OPEN_STATES = [
        "shortlisted", "preparing", "awaiting_approval", "approved",
        "submitting", "submitted", "response", "interview", "offer",
    ]
    await db.applications.create_index(
        [("user_id", ASCENDING), ("job_id", ASCENDING)],
        unique=True,
        partialFilterExpression={"state": {"$in": OPEN_STATES}},
        name="uniq_open_app_per_user_job",
    )
    await db.applications.create_index([("user_id", ASCENDING), ("state", ASCENDING)])
    await db.match_scores.create_index([("user_id", ASCENDING), ("job_id", ASCENDING)], unique=True)
    await db.match_scores.create_index([("user_id", ASCENDING), ("score", DESCENDING)])
    await db.hidden_jobs.create_index([("user_id", ASCENDING), ("job_id", ASCENDING)], unique=True)
    await db.usage_meters.create_index([("user_id", ASCENDING), ("period", ASCENDING)], unique=True)
    await db.score_feedback.create_index([("user_id", ASCENDING), ("match_score_id", ASCENDING)])
    await db.jobs.create_index("last_verified")
    # Phase 3 receipts contract (Founder Directive #2). Empty until Phase 5 wires submission.
    # UNIQUE compound index on (user_id, company_id, req_ref) prevents duplicate receipts by design.
    # Application-layer immutability enforced in `domains/submission_receipts/service.py` (no update path).
    await db.submission_receipts.create_index(
        [("user_id", ASCENDING), ("company_id", ASCENDING), ("req_ref", ASCENDING)],
        unique=True,
        name="uniq_receipt_per_user_company_req",
    )
    # LLM cost ledger (Founder Directive #8) — per-task, per-model.
    await db.llm_costs.create_index([("user_id", ASCENDING), ("ts", DESCENDING)])
    await db.llm_costs.create_index([("task", ASCENDING), ("ts", DESCENDING)])
    # Phase 4 collections
    await db.ai_generations.create_index([("user_id", ASCENDING), ("ts", DESCENDING)])
    await db.ai_generations.create_index([("application_id", ASCENDING), ("ts", DESCENDING)])
    await db.screening_answers.create_index(
        [("user_id", ASCENDING), ("application_id", ASCENDING), ("question_id", ASCENDING)],
        unique=True,
        partialFilterExpression={"application_id": {"$type": "string"}},
        name="uniq_answer_per_app_question",
    )
    await db.screening_answers.create_index([("user_id", ASCENDING), ("application_id", ASCENDING)])
    await db.resume_versions.create_index([("user_id", ASCENDING), ("base", ASCENDING)])
    await db.resume_versions.create_index([("application_id", ASCENDING)])
    # Phase 5 collections
    # authorization_scopes already has an index above; add the (created_at DESC) for latest-lookup.
    await db.authorization_scopes.create_index(
        [("user_id", ASCENDING), ("target", ASCENDING), ("created_at", DESCENDING)],
        name="auth_scope_latest_lookup",
    )
    await db.subscriptions.create_index("user_id", unique=True)
    await db.outcomes.create_index([("user_id", ASCENDING), ("application_id", ASCENDING), ("ts", DESCENDING)])
    # Idempotency for inbound webhook — one outcome per (user_id, ext_message_id).
    await db.outcomes.create_index(
        [("user_id", ASCENDING), ("ext_message_id", ASCENDING)],
        unique=True,
        partialFilterExpression={"ext_message_id": {"$type": "string"}},
        name="uniq_outcome_per_user_ext_msg",
    )
    await db.interviews.create_index([("user_id", ASCENDING), ("application_id", ASCENDING)])
    await db.manual_queue_items.create_index([("user_id", ASCENDING), ("state", ASCENDING)])
    await db.manual_queue_items.create_index("application_id", unique=True)
    # (user_id, ts) index for daily-cap counting is served by (user_id, company_id, req_ref) prefix + ts scan.
    await db.submission_receipts.create_index([("user_id", ASCENDING), ("ts", DESCENDING)],
                                              name="receipts_by_user_ts")
    # Phase 6 collections
    await db.feature_flags.create_index("name", unique=True)
    await db.payment_transactions.create_index("session_id", unique=True)
    await db.payment_transactions.create_index([("user_id", ASCENDING), ("created_at", DESCENDING)])
    await db.support_tickets.create_index([("user_id", ASCENDING), ("created_at", DESCENDING)])
    await db.export_jobs.create_index([("user_id", ASCENDING), ("created_at", DESCENDING)])
    await db.internal_analytics_events.create_index([("ts", DESCENDING)])
    await db.internal_error_events.create_index([("ts", DESCENDING)])

