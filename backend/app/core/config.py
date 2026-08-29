from decimal import Decimal
from functools import lru_cache
from typing import Literal

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
    cooling_base_temperature_c: Decimal = Field(
        default=Decimal("18"),
        validation_alias="COOLING_BASE_TEMPERATURE_C",
    )
    feature_dataset_max_range_days: int = Field(
        default=366,
        ge=1,
        le=1_825,
        validation_alias="FEATURE_DATASET_MAX_RANGE_DAYS",
    )
    feature_dataset_dir: str = Field(
        default="app/data/generated/features",
        validation_alias="FEATURE_DATASET_DIR",
    )
    model_artifact_dir: str = Field(
        default="app/data/generated/models",
        validation_alias="MODEL_ARTIFACT_DIR",
    )
    model_validation_fraction: float = Field(
        default=0.2,
        gt=0,
        le=0.5,
        validation_alias="MODEL_VALIDATION_FRACTION",
    )
    model_min_training_rows: int = Field(
        default=72,
        ge=24,
        le=100_000,
        validation_alias="MODEL_MIN_TRAINING_ROWS",
    )
    zone_risk_heat_anomaly_scale_c: Decimal = Field(
        default=Decimal("5"),
        gt=0,
        le=30,
        validation_alias="ZONE_RISK_HEAT_ANOMALY_SCALE_C",
    )
    zone_risk_temperature_ramp_scale_c_per_hour: Decimal = Field(
        default=Decimal("2"),
        gt=0,
        le=20,
        validation_alias="ZONE_RISK_TEMPERATURE_RAMP_SCALE_C_PER_HOUR",
    )
    zone_risk_temperature_stddev_scale_c: Decimal = Field(
        default=Decimal("5"),
        gt=0,
        le=30,
        validation_alias="ZONE_RISK_TEMPERATURE_STDDEV_SCALE_C",
    )
    zone_risk_uplift_scale_percent: Decimal = Field(
        default=Decimal("25"),
        gt=0,
        le=200,
        validation_alias="ZONE_RISK_UPLIFT_SCALE_PERCENT",
    )
    zone_forecast_max_temperature_age_minutes: int = Field(
        default=120,
        ge=1,
        le=1_440,
        validation_alias="ZONE_FORECAST_MAX_TEMPERATURE_AGE_MINUTES",
    )
    recommendation_min_risk_score: Decimal = Field(
        default=Decimal("65"),
        ge=0,
        le=100,
        validation_alias="RECOMMENDATION_MIN_RISK_SCORE",
    )
    recommendation_min_confidence: Literal["medium", "high"] = Field(
        default="medium",
        validation_alias="RECOMMENDATION_MIN_CONFIDENCE",
    )
    recommendation_expiry_minutes: int = Field(
        default=120,
        ge=5,
        le=720,
        validation_alias="RECOMMENDATION_EXPIRY_MINUTES",
    )
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
    fortyguard_base_url: str = Field(
        default="https://api.fortyguard.com", validation_alias="FORTYGUARD_BASE_URL"
    )
    fortyguard_api_key: str | None = Field(default=None, validation_alias="FORTYGUARD_API_KEY")
    fortyguard_default_granularity: Literal[60, 80, 100] = Field(
        default=80,
        validation_alias="FORTYGUARD_DEFAULT_GRANULARITY",
    )
    fortyguard_request_timeout_seconds: float = Field(
        default=30,
        gt=0,
        le=120,
        validation_alias="FORTYGUARD_REQUEST_TIMEOUT_SECONDS",
    )
    fortyguard_max_heatmap_area_sq_mi: float = Field(
        default=50,
        gt=0,
        le=50,
        validation_alias="FORTYGUARD_MAX_HEATMAP_AREA_SQ_MI",
    )
    fortyguard_max_forecast_hours: int = Field(
        default=12,
        ge=0,
        le=24,
        validation_alias="FORTYGUARD_MAX_FORECAST_HOURS",
    )
    fortyguard_poll_seconds: int = Field(
        default=5,
        ge=1,
        le=60,
        validation_alias="FORTYGUARD_POLL_SECONDS",
    )
    fortyguard_max_poll_seconds: int = Field(
        default=600,
        ge=30,
        le=3600,
        validation_alias="FORTYGUARD_MAX_POLL_SECONDS",
    )
    fortyguard_max_raw_response_bytes: int = Field(
        default=262_144,
        ge=4_096,
        le=1_048_576,
        validation_alias="FORTYGUARD_MAX_RAW_RESPONSE_BYTES",
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

    @field_validator("fortyguard_api_key", mode="before")
    @classmethod
    def empty_fortyguard_api_key_is_none(cls, value: object) -> object:
        """Treat an empty local FortyGuard key as absent without logging its value."""
        if isinstance(value, str) and not value.strip():
            return None
        return value


@lru_cache
def get_settings() -> Settings:
    """Return one cached settings instance for the process."""
    return Settings()
