"""Edge runtime configuration."""

from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class EdgeSettings(BaseSettings):
    """Configuration for Edge Gateway sovereign runtime."""

    model_config = SettingsConfigDict(
        env_prefix="AQUA_EDGE_",
        env_file=".env",
        extra="ignore",
    )

    farm_id: str = "farm-alpha"
    gateway_id: str = "edge-gw-01"

    # SQLite WAL database path for local edge persistence
    db_path: Path = Field(
        default=Path("edge_sovereign.db"),
        description="Path to edge SQLite WAL file",
    )

    # Sync and queue parameters
    sync_interval_seconds: float = 5.0
    batch_size: int = 50
    max_queue_depth: int = 50_000
    max_retries_per_item: int = 10

    # Remote platform API connectivity
    api_url: Optional[str] = "http://localhost:8001/api/v1"
    api_token: Optional[str] = None


edge_settings = EdgeSettings()
