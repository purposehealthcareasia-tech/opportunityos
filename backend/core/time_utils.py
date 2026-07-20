from datetime import datetime, timezone


def utc_now() -> datetime:
    """Timezone-aware UTC now. Never use datetime.utcnow() in this codebase."""
    return datetime.now(timezone.utc)
