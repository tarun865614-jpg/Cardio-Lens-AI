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
    # local | s3. S3 objects are Fernet-encrypted client-side AND stored with SSE-KMS.
    storage_backend: str = "local"
    s3_bucket: str | None = None
    s3_prefix: str = "recordings/"
    s3_region: str | None = None
    s3_endpoint_url: str | None = None  # e.g. MinIO / localstack; leave unset for AWS
    s3_kms_key_id: str | None = None

    # Authentication: local (built-in passwords) | oidc (external identity provider)
    auth_mode: str = "local"
    login_max_failures: int = 5
    login_lockout_minutes: int = 15
    oidc_issuer: str | None = None
    oidc_audience: str | None = None  # API audience expected in access tokens
    oidc_client_id: str | None = None  # public SPA client (PKCE); exposed to the browser
    oidc_jwks_url: str | None = None  # defaults to discovery
    oidc_scopes: str = "openid profile email"
    oidc_role_claim: str = "roles"  # claim holding role(s)/groups
    oidc_role_map: str = "clinician:clinician,researcher:researcher,admin:admin"  # idp-value:role
    oidc_require_mfa: bool = True  # require 'mfa' (or otp/hwk/...) in the amr claim
    oidc_auto_provision: bool = False  # create users on first login (into oidc_default_org)
    oidc_default_org: str | None = None

    # Schema management: create (dev/test convenience) | migrate (alembic; required in production)
    schema_mode: str = "create"

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
            if self.schema_mode != "migrate":
                raise RuntimeError("Production requires CARDIOLENS_SCHEMA_MODE=migrate (run `alembic upgrade head`)")
        if self.auth_mode not in ("local", "oidc"):
            raise RuntimeError("CARDIOLENS_AUTH_MODE must be 'local' or 'oidc'")
        if self.auth_mode == "oidc" and not (self.oidc_issuer and self.oidc_audience and self.oidc_client_id):
            raise RuntimeError("OIDC mode requires CARDIOLENS_OIDC_ISSUER, _AUDIENCE and _CLIENT_ID")
        if self.storage_backend not in ("local", "s3"):
            raise RuntimeError("CARDIOLENS_STORAGE_BACKEND must be 'local' or 's3'")
        if self.storage_backend == "s3" and not self.s3_bucket:
            raise RuntimeError("S3 storage requires CARDIOLENS_S3_BUCKET")

    def role_map(self) -> dict[str, str]:
        out = {}
        for pair in self.oidc_role_map.split(","):
            if ":" in pair:
                k, v = pair.split(":", 1)
                out[k.strip()] = v.strip()
        return out


@lru_cache
def get_settings() -> Settings:
    return Settings()
