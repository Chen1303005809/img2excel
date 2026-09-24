from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the local single-user deployment."""

    model_config = SettingsConfigDict(
        env_prefix="IMAGE_TABLE_",
        env_file=".env",
        extra="ignore",
    )

    data_dir: Path = Path("data")
    database_url: str | None = None
    oracle_database_url: str | None = None
    oracle_config_dir: Path | None = None
    oracle_client_lib_dir: Path | None = None
    oracle_thick_mode: bool = False
    oracle_creator_id: int | None = None
    oracle_creator_lookup_sql: str | None = None
    oracle_application_version: str = "V260123"
    oracle_import_timeout_seconds: int = 30
    backend_host: str = "127.0.0.1"
    backend_port: int = 8000
    frontend_host: str = "127.0.0.1"
    frontend_port: int = 5173
    frontend_origin: str | None = None
    worker_poll_interval: float = 1.0
    worker_concurrency: int = 1
    crawl_concurrency: int | None = None
    ocr_concurrency: int = 1
    lease_seconds: int = 900
    max_image_bytes: int = 50 * 1024 * 1024
    page_timeout_ms: int = 90_000
    image_timeout_seconds: float = 30.0
    allow_private_hosts: bool = False

    @property
    def resolved_data_dir(self) -> Path:
        return self.data_dir.expanduser().resolve()

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.resolved_data_dir / 'app.db'}"

    @property
    def resolved_frontend_origin(self) -> str:
        return self.frontend_origin or f"http://{self.frontend_host}:{self.frontend_port}"

    @property
    def effective_crawl_concurrency(self) -> int:
        return max(1, self.crawl_concurrency or self.worker_concurrency)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.resolved_data_dir.mkdir(parents=True, exist_ok=True)
    return settings
