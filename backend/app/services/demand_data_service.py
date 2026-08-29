"""Application service for importing and reading normalized city demand data."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models.city import City
from app.db.models.demand_observation import DemandObservation
from app.schemas.demand import DemandObservationData
from app.services.audit_service import record_audit_event
from app.services.eia_client import EiaClient, NormalizedDemandRecord, validate_date_range


class DemandDataNotReadyError(Exception):
    """Raised when the configured city has not been seeded yet."""


@dataclass(frozen=True)
class DemandImportResult:
    """Safe summary returned after a synchronous historical EIA import."""

    source: str
    source_area_code: str
    start_utc: datetime
    end_utc: datetime
    fetched_count: int
    created_count: int
    skipped_duplicate_count: int


def import_eia_demand(
    session: Session,
    *,
    start: datetime,
    end: datetime,
    settings: Settings | None = None,
    client: EiaClient | None = None,
) -> DemandImportResult:
    """Fetch a bounded EIA range and persist only observations not already stored."""
    settings = settings or get_settings()
    start_utc, end_utc = validate_date_range(
        start=start,
        end=end,
        max_days=settings.eia_max_import_days,
    )
    city = _get_demo_city(session=session, settings=settings)
    eia_client = client or EiaClient(settings)
    records = eia_client.fetch_hourly_demand(start=start_utc, end=end_utc)

    existing_periods = set(
        session.scalars(
            select(DemandObservation.period_utc).where(
                DemandObservation.city_id == city.id,
                DemandObservation.source == "EIA",
                DemandObservation.source_area_code == eia_client.area_code,
                DemandObservation.period_utc >= start_utc,
                DemandObservation.period_utc <= end_utc,
            )
        ).all()
    )
    new_records = [record for record in records if record.period_utc not in existing_periods]
    for record in new_records:
        session.add(_to_model(city_id=city.id, record=record))

    if new_records:
        session.flush()
    record_audit_event(
        session,
        event_type="demand.eia_imported",
        entity_type="city",
        entity_id=city.id,
        payload={
            "source": "EIA",
            "source_area_code": eia_client.area_code,
            "start_utc": start_utc.isoformat(),
            "end_utc": end_utc.isoformat(),
            "fetched_count": len(records),
            "created_count": len(new_records),
            "skipped_duplicate_count": len(records) - len(new_records),
        },
    )
    session.commit()

    return DemandImportResult(
        source="EIA",
        source_area_code=eia_client.area_code,
        start_utc=start_utc,
        end_utc=end_utc,
        fetched_count=len(records),
        created_count=len(new_records),
        skipped_duplicate_count=len(records) - len(new_records),
    )


def list_demand_observations(
    session: Session,
    *,
    start: datetime,
    end: datetime,
    limit: int = 100,
    offset: int = 0,
    settings: Settings | None = None,
) -> tuple[list[DemandObservationData], int]:
    """Return the configured city's persisted demand observations in chronological order."""
    settings = settings or get_settings()
    start_utc, end_utc = validate_date_range(
        start=start,
        end=end,
        max_days=settings.eia_max_import_days,
    )
    city = _get_demo_city(session=session, settings=settings)
    statement = (
        select(DemandObservation)
        .where(
            DemandObservation.city_id == city.id,
            DemandObservation.period_utc >= start_utc,
            DemandObservation.period_utc <= end_utc,
        )
        .order_by(DemandObservation.period_utc)
    )
    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    observations = session.scalars(statement.offset(offset).limit(limit)).all()
    return [
        DemandObservationData(
            id=observation.id,
            city_id=observation.city_id,
            period_utc=observation.period_utc,
            source=observation.source,
            source_area_code=observation.source_area_code,
            demand_mw=observation.demand_mw,
            is_actual=observation.is_actual,
            quality_flag=observation.quality_flag,
        )
        for observation in observations
    ], total


def _get_demo_city(*, session: Session, settings: Settings) -> City:
    city = session.scalar(
        select(City).where(City.name == settings.demo_city_name, City.country_code == "US")
    )
    if city is None:
        raise DemandDataNotReadyError(
            "The configured demo city is missing. Run python -m app.scripts.seed_city first."
        )
    return city


def _to_model(*, city_id: UUID, record: NormalizedDemandRecord) -> DemandObservation:
    return DemandObservation(
        city_id=city_id,
        period_utc=record.period_utc,
        source=record.source,
        source_area_code=record.source_area_code,
        demand_mw=record.demand_mw,
        is_actual=record.is_actual,
        quality_flag=record.quality_flag,
    )
