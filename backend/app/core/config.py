from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from backend/.env when present."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = Field(default="development", validation_alias="APP_ENV")
    app_name: str = Field(default="energy-grid-api", validation_alias="APP_NAME")
    api_v1_prefix: str = Field(default="/api/v1", validation_alias="API_V1_PREFIX")
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    replay_mode: bool = Field(default=False, validation_alias="REPLAY_MODE")
    database_url: str | None = Field(default=None, validation_alias="DATABASE_URL")
    demo_city_name: str = Field(default="Houston, Texas", validation_alias="DEMO_CITY_NAME")
    demo_timezone: str = Field(default="America/Chicago", validation_alias="DEMO_TIMEZONE")
    eia_base_url: str = Field(default="https://api.eia.gov/v2", validation_alias="EIA_BASE_URL")
    eia_api_key: str | None = Field(default=None, validation_alias="EIA_API_KEY")
    eia_demand_route: str = Field(
        default="electricity/rto/region-data/data", validation_alias="EIA_DEMAND_ROUTE"
    )
    eia_demand_area_code: str = Field(default="ERCO", validation_alias="EIA_DEMAND_AREA_CODE")
    eia_demand_type: str = Field(default="D", validation_alias="EIA_DEMAND_TYPE")
    eia_source_timezone: str = Field(default="UTC", validation_alias="EIA_SOURCE_TIMEZONE")
    eia_request_timeout_seconds: float = Field(
        default=30, gt=0, le=120, validation_alias="EIA_REQUEST_TIMEOUT_SECONDS"
    )
    eia_max_import_days: int = Field(
        default=31,
        ge=1,
        le=366,
        validation_alias="EIA_MAX_IMPORT_DAYS",
    )

    @field_validator("database_url", mode="before")
    @classmethod
    def empty_database_url_is_none(cls, value: object) -> object:
        """Allow Phase 0/replay startup before a database is configured."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("eia_api_key", mode="before")
    @classmethod
    def empty_eia_api_key_is_none(cls, value: object) -> object:
        """Treat an empty local EIA key as absent without logging its value."""
        if isinstance(value, str) and not value.strip():
            return None
        return value


@lru_cache
def get_settings() -> Settings:
    """Return one cached settings instance for the process."""
    return Settings()
