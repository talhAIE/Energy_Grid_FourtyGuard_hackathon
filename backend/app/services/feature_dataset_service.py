"""Build reproducible, quality-labeled model features from persisted demand and temperature data."""

import csv
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models.city import City
from app.db.models.demand_observation import DemandObservation
from app.db.models.zone import Zone
from app.db.models.zone_temperature_observation import ZoneTemperatureObservation
from app.services.audit_service import record_audit_event

FEATURE_SCHEMA_VERSION = "1"
FEATURE_VALUE_SCALE = Decimal("0.001")


class FeatureDatasetError(ValueError):
    """Raised when a requested feature dataset cannot be safely or reproducibly built."""


class FeatureDatasetNotReadyError(Exception):
    """Raised when the configured city or active zone configuration is unavailable."""


@dataclass(frozen=True)
class FeatureRow:
    """One hourly demand target with explicitly aligned weather and calendar features."""

    period_utc: datetime
    period_local: datetime
    target_demand_mw: Decimal
    target_is_actual: bool
    demand_quality_flag: str | None
    city_temperature_c: Decimal | None
    cooling_degree_hours: Decimal | None
    temperature_coverage_weight: Decimal
    available_zone_count: int
    expected_zone_count: int
    temperature_source_kind: str
    feature_quality_status: str
    local_hour: int
    local_day_of_week: int
    is_weekend: bool
    local_month: int
    is_us_federal_holiday: bool

    def as_record(self) -> dict[str, str | int | bool | None]:
        """Return a CSV/JSON-safe record with stable field ordering from the contract."""
        return {
            "period_utc": self.period_utc.isoformat(),
            "period_local": self.period_local.isoformat(),
            "target_demand_mw": _decimal_to_string(self.target_demand_mw),
            "target_is_actual": self.target_is_actual,
            "demand_quality_flag": self.demand_quality_flag,
            "city_temperature_c": _decimal_to_string(self.city_temperature_c),
            "cooling_degree_hours": _decimal_to_string(self.cooling_degree_hours),
            "temperature_coverage_weight": _decimal_to_string(self.temperature_coverage_weight),
            "available_zone_count": self.available_zone_count,
            "expected_zone_count": self.expected_zone_count,
            "temperature_source_kind": self.temperature_source_kind,
            "feature_quality_status": self.feature_quality_status,
            "local_hour": self.local_hour,
            "local_day_of_week": self.local_day_of_week,
            "is_weekend": self.is_weekend,
            "local_month": self.local_month,
            "is_us_federal_holiday": self.is_us_federal_holiday,
        }


@dataclass(frozen=True)
class FeatureDatasetBuildResult:
    """Paths and quality summary for one deterministic feature-dataset build."""

    dataset_version: str
    row_count: int
    csv_path: Path
    quality_report_path: Path
    quality_counts: dict[str, int]


def build_feature_dataset(
    session: Session,
    *,
    start: datetime,
    end: datetime,
    settings: Settings | None = None,
    output_dir: Path | None = None,
) -> FeatureDatasetBuildResult:
    """Build a city-level feature CSV and quality report without filling missing observations."""
    settings = settings or get_settings()
    start_utc, end_utc = _validate_range(start=start, end=end, settings=settings)
    city = _get_demo_city(session=session, settings=settings)
    active_zones = session.scalars(
        select(Zone)
        .where(Zone.city_id == city.id, Zone.active.is_(True))
        .order_by(Zone.code)
    ).all()
    if not active_zones:
        raise FeatureDatasetNotReadyError("No active zones are configured for the demo city.")

    demands = session.scalars(
        select(DemandObservation)
        .where(
            DemandObservation.city_id == city.id,
            DemandObservation.period_utc >= start_utc,
            DemandObservation.period_utc <= end_utc,
        )
        .order_by(DemandObservation.period_utc)
    ).all()
    if not demands:
        raise FeatureDatasetNotReadyError("No demand observations exist for the requested period.")

    zone_weights = {zone.id: Decimal(zone.allocation_weight) for zone in active_zones}
    temperatures_by_period = _latest_temperatures_by_period(
        session=session,
        city_id=city.id,
        active_zone_ids=set(zone_weights),
        start=start_utc,
        end=end_utc,
    )
    local_timezone = _get_timezone(settings.demo_timezone)
    rows = [
        _build_feature_row(
            demand=demand,
            temperatures=temperatures_by_period.get(_ensure_utc(demand.period_utc), {}),
            zone_weights=zone_weights,
            cooling_base=settings.cooling_base_temperature_c,
            local_timezone=local_timezone,
        )
        for demand in demands
    ]
    dataset_version = _dataset_version(
        city_id=city.id,
        start=start_utc,
        end=end_utc,
        cooling_base=settings.cooling_base_temperature_c,
        rows=rows,
    )
    quality_counts = dict(sorted(Counter(row.feature_quality_status for row in rows).items()))
    resolved_output_dir = output_dir or Path(settings.feature_dataset_dir)
    csv_path, quality_report_path = _write_artifacts(
        output_dir=resolved_output_dir,
        dataset_version=dataset_version,
        rows=rows,
        quality_report=_quality_report(
            city=city,
            start=start_utc,
            end=end_utc,
            cooling_base=settings.cooling_base_temperature_c,
            dataset_version=dataset_version,
            rows=rows,
            quality_counts=quality_counts,
        ),
    )
    record_audit_event(
        session,
        event_type="feature_dataset.built",
        entity_type="city",
        entity_id=city.id,
        payload={
            "dataset_version": dataset_version,
            "start_utc": start_utc.isoformat(),
            "end_utc": end_utc.isoformat(),
            "row_count": len(rows),
            "quality_counts": quality_counts,
        },
    )
    session.commit()
    return FeatureDatasetBuildResult(
        dataset_version=dataset_version,
        row_count=len(rows),
        csv_path=csv_path,
        quality_report_path=quality_report_path,
        quality_counts=quality_counts,
    )


def _build_feature_row(
    *,
    demand: DemandObservation,
    temperatures: dict[UUID, ZoneTemperatureObservation],
    zone_weights: dict[UUID, Decimal],
    cooling_base: Decimal,
    local_timezone: ZoneInfo,
) -> FeatureRow:
    available = {
        zone_id: observation
        for zone_id, observation in temperatures.items()
        if (
            zone_id in zone_weights
            and observation.data_status == "available"
            and observation.mean_c is not None
        )
    }
    expected_weight = sum(zone_weights.values(), start=Decimal("0"))
    available_weight = sum(
        (zone_weights[zone_id] for zone_id in available),
        start=Decimal("0"),
    )
    coverage = (
        (available_weight / expected_weight).quantize(FEATURE_VALUE_SCALE, rounding=ROUND_HALF_UP)
        if expected_weight > 0
        else Decimal("0")
    )
    city_temperature = _weighted_temperature(available=available, zone_weights=zone_weights)
    cdh = (
        max(Decimal("0"), city_temperature - cooling_base).quantize(
            FEATURE_VALUE_SCALE,
            rounding=ROUND_HALF_UP,
        )
        if city_temperature is not None
        else None
    )
    quality_status = _temperature_quality_status(
        available_count=len(available),
        expected_count=len(zone_weights),
        coverage=coverage,
    )
    local_time = _ensure_utc(demand.period_utc).astimezone(local_timezone)
    return FeatureRow(
        period_utc=_ensure_utc(demand.period_utc),
        period_local=local_time,
        target_demand_mw=Decimal(demand.demand_mw),
        target_is_actual=demand.is_actual,
        demand_quality_flag=demand.quality_flag,
        city_temperature_c=city_temperature,
        cooling_degree_hours=cdh,
        temperature_coverage_weight=coverage,
        available_zone_count=len(available),
        expected_zone_count=len(zone_weights),
        temperature_source_kind=_temperature_source_kind(available),
        feature_quality_status=quality_status,
        local_hour=local_time.hour,
        local_day_of_week=local_time.weekday(),
        is_weekend=local_time.weekday() >= 5,
        local_month=local_time.month,
        is_us_federal_holiday=local_time.date() in _us_federal_holidays(local_time.year),
    )


def _latest_temperatures_by_period(
    *,
    session: Session,
    city_id: UUID,
    active_zone_ids: set[UUID],
    start: datetime,
    end: datetime,
) -> dict[datetime, dict[UUID, ZoneTemperatureObservation]]:
    observations = session.scalars(
        select(ZoneTemperatureObservation)
        .join(Zone, ZoneTemperatureObservation.zone_id == Zone.id)
        .where(
            Zone.city_id == city_id,
            ZoneTemperatureObservation.observed_for >= start,
            ZoneTemperatureObservation.observed_for <= end,
        )
        .order_by(
            ZoneTemperatureObservation.observed_for,
            ZoneTemperatureObservation.source_retrieved_at.desc(),
        )
    ).all()
    latest: dict[datetime, dict[UUID, ZoneTemperatureObservation]] = defaultdict(dict)
    for observation in observations:
        if observation.zone_id not in active_zone_ids:
            continue
        period = _ensure_utc(observation.observed_for)
        latest[period].setdefault(observation.zone_id, observation)
    return dict(latest)


def _weighted_temperature(
    *,
    available: dict[UUID, ZoneTemperatureObservation],
    zone_weights: dict[UUID, Decimal],
) -> Decimal | None:
    total_weight = sum((zone_weights[zone_id] for zone_id in available), start=Decimal("0"))
    if total_weight <= 0:
        return None
    weighted_sum = sum(
        (
            Decimal(observation.mean_c) * zone_weights[zone_id]
            for zone_id, observation in available.items()
        ),
        start=Decimal("0"),
    )
    return (weighted_sum / total_weight).quantize(FEATURE_VALUE_SCALE, rounding=ROUND_HALF_UP)


def _temperature_quality_status(
    *,
    available_count: int,
    expected_count: int,
    coverage: Decimal,
) -> str:
    if available_count == 0:
        return "missing_temperature"
    if available_count < expected_count or coverage < Decimal("1"):
        return "partial_temperature"
    return "complete"


def _temperature_source_kind(available: dict[UUID, ZoneTemperatureObservation]) -> str:
    if not available:
        return "missing"
    forecast_flags = {observation.is_forecast for observation in available.values()}
    if forecast_flags == {True}:
        return "forecast"
    if forecast_flags == {False}:
        return "actual"
    return "mixed"


def _quality_report(
    *,
    city: City,
    start: datetime,
    end: datetime,
    cooling_base: Decimal,
    dataset_version: str,
    rows: list[FeatureRow],
    quality_counts: dict[str, int],
) -> dict[str, Any]:
    return {
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "dataset_version": dataset_version,
        "city": city.name,
        "timezone": city.timezone,
        "start_utc": start.isoformat(),
        "end_utc": end.isoformat(),
        "cooling_base_temperature_c": _decimal_to_string(cooling_base),
        "row_count": len(rows),
        "quality_counts": quality_counts,
        "actual_demand_rows": sum(row.target_is_actual for row in rows),
        "forecast_demand_rows": sum(not row.target_is_actual for row in rows),
        "temperature_source_counts": dict(
            sorted(Counter(row.temperature_source_kind for row in rows).items())
        ),
        "missing_data_policy": "No demand or temperature values are interpolated.",
    }


def _write_artifacts(
    *,
    output_dir: Path,
    dataset_version: str,
    rows: list[FeatureRow],
    quality_report: dict[str, Any],
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / f"{dataset_version}.csv"
    quality_report_path = output_dir / f"{dataset_version}.quality.json"
    field_names = list(FeatureRow.__dataclass_fields__)
    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=field_names)
        writer.writeheader()
        writer.writerows(row.as_record() for row in rows)
    quality_report_path.write_text(
        json.dumps(quality_report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return csv_path, quality_report_path


def _dataset_version(
    *,
    city_id: UUID,
    start: datetime,
    end: datetime,
    cooling_base: Decimal,
    rows: list[FeatureRow],
) -> str:
    fingerprint = {
        "schema": FEATURE_SCHEMA_VERSION,
        "city_id": str(city_id),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "cooling_base": _decimal_to_string(cooling_base),
        "rows": [row.as_record() for row in rows],
    }
    encoded = json.dumps(fingerprint, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"features-v{FEATURE_SCHEMA_VERSION}-{hashlib.sha256(encoded).hexdigest()[:12]}"


def _validate_range(
    *,
    start: datetime,
    end: datetime,
    settings: Settings,
) -> tuple[datetime, datetime]:
    start_utc = _ensure_utc(start)
    end_utc = _ensure_utc(end)
    if end_utc <= start_utc:
        raise FeatureDatasetError("End time must be later than start time.")
    if end_utc - start_utc > timedelta(days=settings.feature_dataset_max_range_days):
        raise FeatureDatasetError(
            f"Feature dataset range cannot exceed {settings.feature_dataset_max_range_days} days."
        )
    return start_utc, end_utc


def _get_demo_city(*, session: Session, settings: Settings) -> City:
    city = session.scalar(
        select(City).where(City.name == settings.demo_city_name, City.country_code == "US")
    )
    if city is None:
        raise FeatureDatasetNotReadyError(
            "The configured demo city is missing. Run python -m app.scripts.seed_city first."
        )
    return city


def _get_timezone(value: str) -> ZoneInfo:
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise FeatureDatasetError("DEMO_TIMEZONE must be a valid IANA timezone.") from exc


def _ensure_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _decimal_to_string(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def _us_federal_holidays(year: int) -> set[date]:
    """Return observed U.S. federal holiday dates needed for an optional calendar feature."""
    holidays = {
        _observed_date(date(year, 1, 1)),
        _nth_weekday(year, 1, 0, 3),
        _nth_weekday(year, 2, 0, 3),
        _last_weekday(year, 5, 0),
        _observed_date(date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 10, 0, 2),
        _observed_date(date(year, 11, 11)),
        _nth_weekday(year, 11, 3, 4),
        _observed_date(date(year, 12, 25)),
    }
    if year >= 2021:
        holidays.add(_observed_date(date(year, 6, 19)))
    return holidays


def _observed_date(value: date) -> date:
    if value.weekday() == 5:
        return value - timedelta(days=1)
    if value.weekday() == 6:
        return value + timedelta(days=1)
    return value


def _nth_weekday(year: int, month: int, weekday: int, occurrence: int) -> date:
    current = date(year, month, 1)
    offset = (weekday - current.weekday()) % 7
    return current + timedelta(days=offset + (occurrence - 1) * 7)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    next_month = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    current = next_month - timedelta(days=1)
    return current - timedelta(days=(current.weekday() - weekday) % 7)
