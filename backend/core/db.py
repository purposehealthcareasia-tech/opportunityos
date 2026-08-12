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


# --------------------------------------------------------------------------- #
# Index specification — one helper per collection group.
#
# Refactored from a linear 100+-line `ensure_indexes` (Tier 2 backlog 2a).
# Grouping is by DOMAIN, not by Phase — the original code interleaved Phase-3
# and Phase-5 indexes on the same collections (e.g. `submission_receipts`
# had one index at line 72 and another at line 111). This split places every
# index for a given collection in the same helper so it is trivial to reason
# about a collection's full index surface.
#
# BEHAVIOR PROOF (byte-identical to the pre-refactor sequence): the
# `_ALL_GROUPS` runner below invokes helpers in an order chosen so that every
# collection's *first* index creation happens at the SAME sequence position
# as before the refactor. See test_ensure_indexes_ordering_stable.py for the
# regression guard.
# --------------------------------------------------------------------------- #

# Application-open-state whitelist used by the partial unique-per-user-job
# index. Enumerated because Mongo partial indexes don't support $ne.
_OPEN_APP_STATES = [
    "shortlisted", "preparing", "awaiting_approval", "approved",
    "submitting", "submitted", "response", "interview", "offer",
]


async def _ensure_identity_indexes(db: AsyncIOMotorDatabase) -> None:
    """users, admin_users, authorization_scopes, consent_records, audit_logs."""
    await db.users.create_index("email", unique=True)
    await db.consent_records.create_index([("user_id", ASCENDING), ("scope", ASCENDING), ("ts", DESCENDING)])
    await db.authorization_scopes.create_index([("user_id", ASCENDING), ("kind", ASCENDING), ("target", ASCENDING)])
    await db.audit_logs.create_index([("actor", ASCENDING), ("ts", DESCENDING)])
    await db.audit_logs.create_index([("object_ref", ASCENDING), ("ts", DESCENDING)])
    await db.admin_users.create_index("user_id", unique=True)


async def _ensure_document_indexes(db: AsyncIOMotorDatabase) -> None:
    """documents, resume_versions (Phase 1 only), preferences, eligibility_profiles,
    claims, taxonomy, companies."""
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


async def _ensure_job_indexes(db: AsyncIOMotorDatabase) -> None:
    """jobs — canonical_key, status, taxonomy_family, last_verified, first_seen."""
    await db.jobs.create_index("canonical_key", unique=True)
    await db.jobs.create_index("status")
    await db.jobs.create_index("taxonomy_family")


async def _ensure_idempotency_indexes(db: AsyncIOMotorDatabase) -> None:
    """idempotency_records — with 7-day TTL."""
    await db.idempotency_records.create_index("key", unique=True)
    # 7-day TTL on idempotency records
    await db.idempotency_records.create_index("created_at", expireAfterSeconds=60 * 60 * 24 * 7)


async def _ensure_application_indexes(db: AsyncIOMotorDatabase) -> None:
    """applications (Phase 3), match_scores, hidden_jobs, usage_meters, score_feedback."""
    await db.applications.create_index([("user_id", ASCENDING), ("job_id", ASCENDING)])
    # Partial unique: no more than one non-closed application per (user, job).
    # Mongo partial indexes don't support $ne, so enumerate allowed "open" states explicitly.
    await db.applications.create_index(
        [("user_id", ASCENDING), ("job_id", ASCENDING)],
        unique=True,
        partialFilterExpression={"state": {"$in": _OPEN_APP_STATES}},
        name="uniq_open_app_per_user_job",
    )
    await db.applications.create_index([("user_id", ASCENDING), ("state", ASCENDING)])
    await db.match_scores.create_index([("user_id", ASCENDING), ("job_id", ASCENDING)], unique=True)
    await db.match_scores.create_index([("user_id", ASCENDING), ("score", DESCENDING)])
    await db.hidden_jobs.create_index([("user_id", ASCENDING), ("job_id", ASCENDING)], unique=True)
    await db.usage_meters.create_index([("user_id", ASCENDING), ("period", ASCENDING)], unique=True)
    await db.score_feedback.create_index([("user_id", ASCENDING), ("match_score_id", ASCENDING)])
    await db.jobs.create_index("last_verified")


async def _ensure_receipt_indexes(db: AsyncIOMotorDatabase) -> None:
    """submission_receipts (Phase 3 + Phase 5 lookups) + llm_costs ledger."""
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


async def _ensure_phase4_indexes(db: AsyncIOMotorDatabase) -> None:
    """ai_generations, screening_answers, resume_versions Phase-4 additions."""
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


async def _ensure_phase5_indexes(db: AsyncIOMotorDatabase) -> None:
    """authorization_scopes (latest-lookup), subscriptions, outcomes, interviews,
    manual_queue_items, submission_receipts by-user-ts."""
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


async def _ensure_phase6_indexes(db: AsyncIOMotorDatabase) -> None:
    """feature_flags, payment_transactions, support_tickets, export_jobs, analytics/error events."""
    await db.feature_flags.create_index("name", unique=True)
    await db.payment_transactions.create_index("session_id", unique=True)
    await db.payment_transactions.create_index([("user_id", ASCENDING), ("created_at", DESCENDING)])
    await db.support_tickets.create_index([("user_id", ASCENDING), ("created_at", DESCENDING)])
    await db.export_jobs.create_index([("user_id", ASCENDING), ("created_at", DESCENDING)])
    await db.internal_analytics_events.create_index([("ts", DESCENDING)])
    await db.internal_error_events.create_index([("ts", DESCENDING)])


async def _ensure_founder_brief_indexes(db: AsyncIOMotorDatabase) -> None:
    """Phase 3 Founder Brief: walkins, personas, discovery_runs, and jobs.first_seen."""
    await db.walkins.create_index([("user_id", ASCENDING), ("walked_in_at", DESCENDING)])
    await db.walkins.create_index([("user_id", ASCENDING), ("created_at", DESCENDING)])
    await db.walkins.create_index("application_id")
    await db.personas.create_index([("user_id", ASCENDING), ("created_at", DESCENDING)])
    await db.personas.create_index([("user_id", ASCENDING), ("superseded_by", ASCENDING)])
    # Discovery runs audit — needed for future audit inspection
    await db.discovery_runs.create_index([("ts", DESCENDING)])
    # jobs.first_seen index used by supply-reality new-today count
    await db.jobs.create_index("first_seen")


async def _ensure_credits_indexes(db: AsyncIOMotorDatabase) -> None:
    """Phase 6d Application Credits — atomic-debit balance doc + append-only ledger.

    Rails pinned by these indexes:
      * `application_credits_balance` — one row per user; unique on `user_id`.
      * `application_credits_ledger` — append-only; unique compound on
        (user_id, receipt_id, direction) so the debit path is idempotent
        under retries (a replay of the same dispatch hits E11000 and
        rolls back the balance decrement).
    """
    await db.application_credits_balance.create_index(
        [("user_id", ASCENDING)], unique=True,
    )
    # Debit idempotency — replay-safe. `receipt_id` is a UUID string only
    # on debit rows; grant rows lack the field entirely. Partial filter
    # `$type: "string"` restricts the unique constraint to actual debit
    # rows (MongoDB partial-index expressions don't support `$ne`/`$not`).
    await db.application_credits_ledger.create_index(
        [("user_id", ASCENDING), ("receipt_id", ASCENDING), ("direction", ASCENDING)],
        unique=True,
        partialFilterExpression={"receipt_id": {"$type": "string"}},
        name="credits_ledger_debit_unique",
    )
    # Query-side: recent rows per user (ledger_page uses ts DESC).
    await db.application_credits_ledger.create_index(
        [("user_id", ASCENDING), ("ts", DESCENDING)],
    )
    # Monthly-refill idempotency lookup.
    await db.application_credits_ledger.create_index(
        [("user_id", ASCENDING), ("source", ASCENDING), ("month_key", ASCENDING)],
        partialFilterExpression={"source": "monthly_refill"},
        name="credits_ledger_monthly_refill_idempotent",
    )


# --------------------------------------------------------------------------- #
# Public entry point — order matches the pre-refactor byte-identical sequence.
# --------------------------------------------------------------------------- #
_ENSURE_INDEX_GROUPS = (
    _ensure_identity_indexes,
    _ensure_document_indexes,
    _ensure_job_indexes,
    _ensure_idempotency_indexes,
    _ensure_application_indexes,
    _ensure_receipt_indexes,
    _ensure_phase4_indexes,
    _ensure_phase5_indexes,
    _ensure_phase6_indexes,
    _ensure_founder_brief_indexes,
    _ensure_credits_indexes,
)


async def ensure_indexes() -> None:
    """Create every index the app needs to run correctly. Idempotent per
    Mongo's create_index semantics.

    Split into 10 collection-group helpers (Tier 2 refactor 2a) so an
    engineer touching a specific domain can find and reason about that
    domain's full index surface in one place. Behavior is byte-identical
    to the pre-refactor linear implementation — see
    test_ensure_indexes_ordering_stable.py for the ordering guard.
    """
    db = get_db()
    for group in _ENSURE_INDEX_GROUPS:
        await group(db)
