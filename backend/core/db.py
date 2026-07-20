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
