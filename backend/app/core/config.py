"""Environment-based configuration. All settings are prefixed with BITGUARD_."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BITGUARD_", env_file=".env", extra="ignore")

    env: str = "development"
    database_url: str = "postgresql+asyncpg://bitguard:bitguard@localhost:5432/bitguard"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = Field(default="dev-only-insecure-secret-change-me-0123456789", min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    storage_dir: Path = Path("./storage")
    model_dir: Path = Path("../ml/models")
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173", "http://localhost:8080"]
    max_upload_mb: int = 512
    celery_eager: bool = False
    ingestion_checkpoint_every: int = 500
    ingestion_max_retries: int = 3
    bootstrap_admin_email: str | None = None
    rate_limit_storage: str | None = None  # defaults to redis_url
    login_rate_limit: str = "10/minute"
    default_rate_limit: str = "600/minute"
    max_json_body_kb: int = 1024
    bootstrap_admin_password: str | None = None
    static_dir: Path | None = None  # built SPA to serve from the API process (single-service deployments)

    @field_validator("database_url", mode="before")
    @classmethod
    def _asyncpg_scheme(cls, v: object) -> object:
        """Managed Postgres providers (Render, Heroku) hand out postgres:// or postgresql:// URLs."""
        if isinstance(v, str):
            for prefix in ("postgres://", "postgresql://"):
                if v.startswith(prefix):
                    return "postgresql+asyncpg://" + v[len(prefix) :]
        return v

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("["):
                import json

                return json.loads(v)
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    def validate_for_runtime(self) -> None:
        if self.is_production and ("dev-only" in self.jwt_secret or "change-me" in self.jwt_secret):
            raise RuntimeError("BITGUARD_JWT_SECRET must be set to a strong secret in production")


@lru_cache
def get_settings() -> Settings:
    return Settings()
