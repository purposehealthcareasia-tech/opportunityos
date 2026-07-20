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


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
