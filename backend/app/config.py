"""Runtime configuration. All secrets come from the environment, never from code."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CARDIOLENS_", env_file=".env", extra="ignore")

    env: str = Field(default="development", description="development | test | production")
    database_url: str = "sqlite:///./cardiolens.db"

    # Secret used to sign access tokens. MUST be overridden outside development.
    jwt_secret: str = "dev-only-insecure-secret-change-me"
    jwt_ttl_minutes: int = 60

    # Fernet key (urlsafe base64, 32 bytes) for encrypting audio at rest.
    # If unset in development a key is derived from jwt_secret; production refuses to start.
    storage_key: str | None = None
    storage_dir: Path = Path("./data/recordings")

    max_upload_mb: int = 20
    retention_days_default: int = 365

    # Model inference
    model_backend: str = Field(default="none", description="none | http")
    model_service_url: str | None = None
    model_service_timeout_s: float = 10.0
    model_card_path: Path | None = None

    cors_origins: str = "http://localhost:5173"

    seed_demo_data: bool = True

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    def validate_for_runtime(self) -> None:
        if self.is_production:
            if self.jwt_secret.startswith("dev-only") or len(self.jwt_secret) < 32:
                raise RuntimeError("CARDIOLENS_JWT_SECRET must be set to a strong secret in production")
            if not self.storage_key:
                raise RuntimeError("CARDIOLENS_STORAGE_KEY must be set in production")
            if self.seed_demo_data:
                raise RuntimeError("Demo data seeding must be disabled in production")


@lru_cache
def get_settings() -> Settings:
    return Settings()
