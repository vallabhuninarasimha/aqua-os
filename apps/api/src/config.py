"""Application configuration for Aqua OS API service."""

from typing import List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven settings for Aqua OS API.

    Development defaults are local-first (SQLite default, local CORS).
    Production configurations must be supplied via AQUA_* environment variables.
    """

    model_config = SettingsConfigDict(
        env_prefix="AQUA_",
        env_file=".env",
        extra="ignore",
    )

    app_name: str = "Aqua OS API"
    environment: str = "development"
    debug: bool = False
    api_prefix: str = "/api/v1"

    # Default Farm ID
    default_farm_id: str = "farm-alpha"

    # Database settings:
    # Defaults to local SQLite for frictionless local development.
    # Set to PostgreSQL / TimescaleDB via AQUA_DATABASE_URL for containerized/production use.
    database_url: str = Field(
        default="sqlite:///aqua_os.db",
        description="Database connection URI (SQLite or PostgreSQL+TimescaleDB)",
    )

    # Security & CORS:
    cors_origins: List[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:8000",
        ],
        description="Allowed CORS origins for dashboard/PWA clients",
    )

    # JWT Authentication secrets & lifetimes
    jwt_secret_key: str = Field(
        default="aqua_secure_dev_secret_key_change_in_production_32chars",
        description="Secret key for signing access tokens. MUST be overridden in production.",
    )
    jwt_access_token_expire_minutes: int = Field(
        default=60,
        description="JWT token validity lifetime in minutes",
    )

    # Optional Edge API key for direct hardware gateway authentication
    api_key: Optional[str] = Field(
        default=None,
        description="Pre-shared secret for Edge-to-Cloud authentication.",
    )

    # Ingestion rate limits & guardrails
    max_telemetry_batch_size: int = 100
    dead_man_timeout_seconds: int = 180


settings = Settings()
