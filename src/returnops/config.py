from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RETURNOPS_", env_file=".env", extra="ignore")

    environment: str = "dev"
    database_url: str = "sqlite+pysqlite:///./returnops.db"
    payment_base_url: str = "http://payment:8090"
    payment_webhook_secret: str = "dev-webhook-secret"
    payment_simulation_mode: str = "normal"
    worker_poll_seconds: float = 0.5
    worker_lease_seconds: int = 30
    max_dispatch_attempts: int = 3
    high_value_threshold: int = 50000  # minor units, e.g. cents


@lru_cache
def get_settings() -> Settings:
    return Settings()
