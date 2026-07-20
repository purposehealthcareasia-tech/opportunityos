from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parent.parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    MONGO_URL: str = "mongodb://localhost:27017"
    DB_NAME: str = "opportunityos"
    JWT_SECRET: str = "dev-change-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRES_HOURS: int = 24
    POLICY_TEXT_VERSION: str = "1.0"
    STORAGE_ROOT: str = "/app/backend/storage"
    EMERGENT_LLM_KEY: str = ""
    MAX_UPLOAD_MB: int = 10
    INTERNAL_SERVICE_TOKEN: str = ""
    JOB_STALENESS_DAYS: int = 14

    # ---- Phase 6 · Auth hardening ---------------------------------------
    # Cookie/session config.
    SESSION_COOKIE_NAME: str = "oppos_session"
    SESSION_TTL_HOURS: int = 24
    SESSION_COOKIE_SECURE: bool = True  # preview + prod both HTTPS; local dev flips this to False.
    SESSION_COOKIE_SAMESITE_USER: str = "lax"    # user sessions → SameSite=Lax
    SESSION_COOKIE_SAMESITE_ADMIN: str = "strict"  # admin/support → SameSite=Strict
    CSRF_COOKIE_NAME: str = "oppos_csrf"
    CSRF_HEADER_NAME: str = "X-CSRF-Token"

    # Explicit CORS allowlist (comma-separated). Empty → dev-permissive.
    CORS_ALLOW_ORIGINS: str = ""

    # Deployment mode. In PROD_MODE=true, CI_TEST_ISSUER_ENABLED MUST be false
    # (server refuses to start otherwise). This is the fail-fast guard for
    # the CI-only Bearer issuer, per founder amendment 3.
    PROD_MODE: bool = False
    CI_TEST_ISSUER_ENABLED: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
