from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from backend/.env when present."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = Field(default="development", validation_alias="APP_ENV")
    app_name: str = Field(default="energy-grid-api", validation_alias="APP_NAME")
    api_v1_prefix: str = Field(default="/api/v1", validation_alias="API_V1_PREFIX")
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    replay_mode: bool = Field(default=False, validation_alias="REPLAY_MODE")


@lru_cache
def get_settings() -> Settings:
    """Return one cached settings instance for the process."""
    return Settings()

