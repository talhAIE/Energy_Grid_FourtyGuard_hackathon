"""Train and run the transparent Phase 8 city-level baseline demand model."""

import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models.city import City
from app.db.models.demand_observation import DemandObservation
from app.db.models.model_version import ModelVersion
from app.db.models.zone import Zone
from app.db.models.zone_temperature_observation import ZoneTemperatureObservation
from app.services.audit_service import record_audit_event
from app.services.feature_dataset_service import FEATURE_SCHEMA_VERSION, _us_federal_holidays

ALGORITHM = "ordinary_least_squares_linear_regression_v1"
ARTIFACT_SCHEMA_VERSION = "1"
FEATURE_COLUMNS = (
    "cooling_degree_hours",
    "local_hour",
    "local_day_of_week",
    "is_weekend",
    "local_month",
    "is_us_federal_holiday",
    "lag_demand_1h_mw",
    "lag_demand_24h_mw",
)
QUALITY_POLICY = "complete_temperature_only"
METRIC_SCALE = Decimal("0.001")


class ModelTrainingError(ValueError):
    """Raised when a feature dataset cannot produce a safe baseline model."""


class ModelNotAvailableError(Exception):
    """Raised when a city has no active, usable model artifact."""


class ModelArtifactError(Exception):
    """Raised when a stored model artifact is absent or malformed."""


class ForecastInputError(ValueError):
    """Raised when the next forecast time lacks complete temperature or lag inputs."""


@dataclass(frozen=True)
class DatasetRow:
    """One validated Phase 7 CSV row used to create baseline regression examples."""

    period_utc: datetime
    target_demand_mw: float
    target_is_actual: bool
    cooling_degree_hours: float | None
    feature_quality_status: str
    local_hour: int
    local_day_of_week: int
    is_weekend: bool
    local_month: int
    is_us_federal_holiday: bool


@dataclass(frozen=True)
class TrainingExample:
    """One chronological supervised-learning observation with materialized lag inputs."""

    period_utc: datetime
    target_demand_mw: float
    feature_values: tuple[float, ...]


@dataclass(frozen=True)
class ModelTrainingResult:
    """Safe model-version details returned by the training script."""

    version: str
    algorithm: str
    source_dataset_version: str
    training_row_count: int
    validation_row_count: int
    mae_mw: Decimal
    rmse_mw: Decimal
    mape_percent: Decimal | None
    artifact_path: Path
    validation_predictions_path: Path
    reused_existing_version: bool


@dataclass(frozen=True)
class ActiveModelSummary:
    """The active model metadata made available to the API without exposing artifact contents."""

    version: str
    algorithm: str
    source_dataset_version: str
    feature_schema_version: str
    quality_policy: str
    feature_columns: list[str]
    trained_from: datetime
    trained_to: datetime
    training_row_count: int
    validation_row_count: int
    mae_mw: Decimal
    rmse_mw: Decimal
    mape_percent: Decimal | None
    activated_at: datetime | None


@dataclass(frozen=True)
class ForecastResult:
    """One city-level demand estimate with the exact inputs used to make it."""

    model_version: str
    algorithm: str
    forecast_for: datetime
    predicted_demand_mw: Decimal
    prediction_was_clamped: bool
    city_temperature_c: Decimal
    cooling_degree_hours: Decimal
    temperature_source_kind: str
    feature_quality_status: str
    lag_demand_1h_mw: Decimal
    lag_demand_24h_mw: Decimal


def train_baseline_model(
    session: Session,
    *,
    dataset_path: Path,
    settings: Settings | None = None,
) -> ModelTrainingResult:
    """Fit and activate one deterministic OLS model using a chronological holdout split."""
    settings = settings or get_settings()
    dataset_bytes = _read_dataset_bytes(dataset_path)
    dataset_sha256 = hashlib.sha256(dataset_bytes).hexdigest()
    dataset_rows = _parse_dataset_rows(dataset_bytes)
    examples = _build_training_examples(dataset_rows)
    train_examples, validation_examples = _chronological_split(examples=examples, settings=settings)
    coefficients, intercept = _fit_ordinary_least_squares(train_examples)
    validation_predictions = _predict_examples(
        examples=validation_examples,
        coefficients=coefficients,
        intercept=intercept,
    )
    mae_mw, rmse_mw, mape_percent = _metrics(validation_predictions)

    city = _get_demo_city(session=session, settings=settings)
    source_dataset_version = dataset_path.stem
    version = _model_version(
        dataset_sha256=dataset_sha256,
        validation_fraction=settings.model_validation_fraction,
    )
    artifact_path, validation_path = _artifact_paths(settings=settings, version=version)
    existing = session.scalar(
        select(ModelVersion).where(ModelVersion.city_id == city.id, ModelVersion.version == version)
    )
    if existing is not None:
        _activate_model(session=session, city_id=city.id, model=existing)
        record_audit_event(
            session,
            event_type="model.training_reused",
            entity_type="model_version",
            entity_id=existing.id,
            payload={
                "version": existing.version,
                "source_dataset_version": existing.source_dataset_version,
            },
        )
        session.commit()
        return _training_result(existing, reused_existing_version=True)

    _write_model_artifacts(
        artifact_path=artifact_path,
        validation_path=validation_path,
        version=version,
        source_dataset_version=source_dataset_version,
        dataset_sha256=dataset_sha256,
        coefficients=coefficients,
        intercept=intercept,
        train_examples=train_examples,
        validation_predictions=validation_predictions,
        mae_mw=mae_mw,
        rmse_mw=rmse_mw,
        mape_percent=mape_percent,
    )
    model = ModelVersion(
        city_id=city.id,
        version=version,
        algorithm=ALGORITHM,
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        feature_columns=list(FEATURE_COLUMNS),
        quality_policy=QUALITY_POLICY,
        source_dataset_version=source_dataset_version,
        training_data_sha256=dataset_sha256,
        trained_from=train_examples[0].period_utc,
        trained_to=validation_examples[-1].period_utc,
        training_row_count=len(train_examples),
        validation_row_count=len(validation_examples),
        mae_mw=mae_mw,
        rmse_mw=rmse_mw,
        mape_percent=mape_percent,
        artifact_path=str(artifact_path.resolve()),
        validation_predictions_path=str(validation_path.resolve()),
        artifact_metadata={
            "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
            "validation_fraction": settings.model_validation_fraction,
            "feature_columns": list(FEATURE_COLUMNS),
        },
        is_active=True,
        activated_at=datetime.now(UTC),
    )
    _activate_model(session=session, city_id=city.id, model=model)
    session.add(model)
    session.flush()
    record_audit_event(
        session,
        event_type="model.trained",
        entity_type="model_version",
        entity_id=model.id,
        payload={
            "version": model.version,
            "algorithm": model.algorithm,
            "source_dataset_version": model.source_dataset_version,
            "training_row_count": model.training_row_count,
            "validation_row_count": model.validation_row_count,
            "mae_mw": _decimal_text(model.mae_mw),
            "rmse_mw": _decimal_text(model.rmse_mw),
            "mape_percent": _decimal_text(model.mape_percent),
        },
    )
    session.commit()
    return _training_result(model, reused_existing_version=False)


def get_active_model_summary(
    session: Session,
    *,
    settings: Settings | None = None,
) -> ActiveModelSummary:
    """Return the one explicit active model for the configured city."""
    city = _get_demo_city(session=session, settings=settings or get_settings())
    model = _get_active_model(session=session, city_id=city.id)
    return _summary(model)


def run_city_forecast(
    session: Session,
    *,
    forecast_for: datetime | None = None,
    settings: Settings | None = None,
) -> ForecastResult:
    """Estimate demand for a requested or next available complete-temperature time slot."""
    settings = settings or get_settings()
    city = _get_demo_city(session=session, settings=settings)
    model = _get_active_model(session=session, city_id=city.id)
    artifact = _load_artifact(model=model, settings=settings)
    if forecast_for is not None:
        target_time = _ensure_utc(forecast_for)
        feature_values, inputs = _forecast_features(
            session=session,
            city=city,
            forecast_for=target_time,
            settings=settings,
        )
    else:
        target_time, feature_values, inputs = _next_usable_forecast_inputs(
            session=session,
            city=city,
            settings=settings,
        )
    predicted_value = float(artifact["intercept"]) + float(
        np.dot(
            np.asarray(feature_values, dtype=float),
            np.asarray(artifact["coefficients"], dtype=float),
        )
    )
    clamped = predicted_value < 0
    predicted = max(0.0, predicted_value)
    result = ForecastResult(
        model_version=model.version,
        algorithm=model.algorithm,
        forecast_for=target_time,
        predicted_demand_mw=_metric_decimal(predicted),
        prediction_was_clamped=clamped,
        city_temperature_c=inputs["city_temperature_c"],
        cooling_degree_hours=inputs["cooling_degree_hours"],
        temperature_source_kind=inputs["temperature_source_kind"],
        feature_quality_status="complete",
        lag_demand_1h_mw=inputs["lag_demand_1h_mw"],
        lag_demand_24h_mw=inputs["lag_demand_24h_mw"],
    )
    record_audit_event(
        session,
        event_type="forecast.generated",
        entity_type="model_version",
        entity_id=model.id,
        payload={
            "forecast_for": target_time.isoformat(),
            "predicted_demand_mw": _decimal_text(result.predicted_demand_mw),
            "prediction_was_clamped": clamped,
            "temperature_source_kind": result.temperature_source_kind,
        },
    )
    session.commit()
    return result


def _read_dataset_bytes(dataset_path: Path) -> bytes:
    if dataset_path.suffix.lower() != ".csv":
        raise ModelTrainingError("The Phase 7 dataset must be a CSV file.")
    try:
        return dataset_path.read_bytes()
    except OSError as exc:
        raise ModelTrainingError("The requested feature dataset could not be read.") from exc


def _parse_dataset_rows(dataset_bytes: bytes) -> list[DatasetRow]:
    try:
        text = dataset_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ModelTrainingError("The feature dataset must be UTF-8 encoded.") from exc
    reader = csv.DictReader(text.splitlines())
    required_columns = {
        "period_utc",
        "target_demand_mw",
        "target_is_actual",
        "cooling_degree_hours",
        "feature_quality_status",
        "local_hour",
        "local_day_of_week",
        "is_weekend",
        "local_month",
        "is_us_federal_holiday",
    }
    actual_columns = set(reader.fieldnames or [])
    missing_columns = sorted(required_columns - actual_columns)
    if missing_columns:
        raise ModelTrainingError(
            f"The feature dataset is missing columns: {', '.join(missing_columns)}."
        )

    rows: list[DatasetRow] = []
    seen_timestamps: set[datetime] = set()
    for line_number, record in enumerate(reader, start=2):
        try:
            period = _ensure_utc(datetime.fromisoformat(_required(record, "period_utc")))
            if period in seen_timestamps:
                raise ModelTrainingError("The feature dataset contains duplicate UTC timestamps.")
            seen_timestamps.add(period)
            target = float(_required(record, "target_demand_mw"))
            if not np.isfinite(target) or target < 0:
                raise ValueError("target_demand_mw must be a non-negative finite value")
            cdh_text = record.get("cooling_degree_hours")
            cdh = float(cdh_text) if cdh_text not in (None, "") else None
            if cdh is not None and (not np.isfinite(cdh) or cdh < 0):
                raise ValueError("cooling_degree_hours must be a non-negative finite value")
            rows.append(
                DatasetRow(
                    period_utc=period,
                    target_demand_mw=target,
                    target_is_actual=_parse_bool(_required(record, "target_is_actual")),
                    cooling_degree_hours=cdh,
                    feature_quality_status=_required(record, "feature_quality_status"),
                    local_hour=_parse_int(record, "local_hour", minimum=0, maximum=23),
                    local_day_of_week=_parse_int(record, "local_day_of_week", minimum=0, maximum=6),
                    is_weekend=_parse_bool(_required(record, "is_weekend")),
                    local_month=_parse_int(record, "local_month", minimum=1, maximum=12),
                    is_us_federal_holiday=_parse_bool(_required(record, "is_us_federal_holiday")),
                )
            )
        except (TypeError, ValueError) as exc:
            if isinstance(exc, ModelTrainingError):
                raise
            raise ModelTrainingError(
                f"Invalid feature-dataset row at line {line_number}: {exc}."
            ) from exc
    if not rows:
        raise ModelTrainingError("The feature dataset has no data rows.")
    return sorted(rows, key=lambda row: row.period_utc)


def _build_training_examples(rows: list[DatasetRow]) -> list[TrainingExample]:
    actual_demand = {row.period_utc: row.target_demand_mw for row in rows if row.target_is_actual}
    examples: list[TrainingExample] = []
    for row in rows:
        lag_one = actual_demand.get(row.period_utc - timedelta(hours=1))
        lag_day = actual_demand.get(row.period_utc - timedelta(hours=24))
        if (
            not row.target_is_actual
            or row.feature_quality_status != "complete"
            or row.cooling_degree_hours is None
            or lag_one is None
            or lag_day is None
        ):
            continue
        examples.append(
            TrainingExample(
                period_utc=row.period_utc,
                target_demand_mw=row.target_demand_mw,
                feature_values=(
                    row.cooling_degree_hours,
                    float(row.local_hour),
                    float(row.local_day_of_week),
                    float(row.is_weekend),
                    float(row.local_month),
                    float(row.is_us_federal_holiday),
                    lag_one,
                    lag_day,
                ),
            )
        )
    return examples


def _chronological_split(
    *,
    examples: list[TrainingExample],
    settings: Settings,
) -> tuple[list[TrainingExample], list[TrainingExample]]:
    if len(examples) < settings.model_min_training_rows + 1:
        raise ModelTrainingError(
            "Not enough eligible rows to train. Use a longer complete-temperature dataset."
        )
    split_at = int(len(examples) * (1 - settings.model_validation_fraction))
    training = examples[:split_at]
    validation = examples[split_at:]
    if len(training) < settings.model_min_training_rows or not validation:
        raise ModelTrainingError(
            "The chronological train/validation split does not meet MODEL_MIN_TRAINING_ROWS."
        )
    return training, validation


def _fit_ordinary_least_squares(examples: list[TrainingExample]) -> tuple[np.ndarray, float]:
    matrix = np.asarray([example.feature_values for example in examples], dtype=float)
    target = np.asarray([example.target_demand_mw for example in examples], dtype=float)
    design_matrix = np.column_stack((np.ones(len(matrix)), matrix))
    try:
        parameters, _, _, _ = np.linalg.lstsq(design_matrix, target, rcond=None)
    except np.linalg.LinAlgError as exc:
        raise ModelTrainingError("The baseline regression could not be fitted safely.") from exc
    if not np.all(np.isfinite(parameters)):
        raise ModelTrainingError("The baseline regression produced non-finite parameters.")
    return parameters[1:], float(parameters[0])


def _predict_examples(
    *,
    examples: list[TrainingExample],
    coefficients: np.ndarray,
    intercept: float,
) -> list[tuple[TrainingExample, float]]:
    return [
        (example, float(intercept + np.dot(np.asarray(example.feature_values), coefficients)))
        for example in examples
    ]


def _metrics(
    predictions: list[tuple[TrainingExample, float]],
) -> tuple[Decimal, Decimal, Decimal | None]:
    actual = np.asarray([example.target_demand_mw for example, _ in predictions], dtype=float)
    predicted = np.asarray([prediction for _, prediction in predictions], dtype=float)
    errors = predicted - actual
    mae = float(np.mean(np.abs(errors)))
    rmse = float(np.sqrt(np.mean(np.square(errors))))
    non_zero_actual = actual[actual != 0]
    mape = (
        float(np.mean(np.abs(errors[actual != 0] / non_zero_actual)) * 100)
        if len(non_zero_actual)
        else None
    )
    return (
        _metric_decimal(mae),
        _metric_decimal(rmse),
        _metric_decimal(mape) if mape is not None else None,
    )


def _model_version(*, dataset_sha256: str, validation_fraction: float) -> str:
    fingerprint = json.dumps(
        {
            "algorithm": ALGORITHM,
            "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
            "dataset_sha256": dataset_sha256,
            "feature_columns": FEATURE_COLUMNS,
            "quality_policy": QUALITY_POLICY,
            "validation_fraction": validation_fraction,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"baseline-ols-v1-{hashlib.sha256(fingerprint.encode('utf-8')).hexdigest()[:12]}"


def _artifact_paths(*, settings: Settings, version: str) -> tuple[Path, Path]:
    output_dir = Path(settings.model_artifact_dir)
    return output_dir / f"{version}.json", output_dir / f"{version}.validation.csv"


def _write_model_artifacts(
    *,
    artifact_path: Path,
    validation_path: Path,
    version: str,
    source_dataset_version: str,
    dataset_sha256: str,
    coefficients: np.ndarray,
    intercept: float,
    train_examples: list[TrainingExample],
    validation_predictions: list[tuple[TrainingExample, float]],
    mae_mw: Decimal,
    rmse_mw: Decimal,
    mape_percent: Decimal | None,
) -> None:
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact = {
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "version": version,
        "algorithm": ALGORITHM,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "feature_columns": list(FEATURE_COLUMNS),
        "quality_policy": QUALITY_POLICY,
        "source_dataset_version": source_dataset_version,
        "training_data_sha256": dataset_sha256,
        "intercept": intercept,
        "coefficients": [float(value) for value in coefficients],
        "training_period": {
            "start": train_examples[0].period_utc.isoformat(),
            "end": train_examples[-1].period_utc.isoformat(),
        },
        "validation_period": {
            "start": validation_predictions[0][0].period_utc.isoformat(),
            "end": validation_predictions[-1][0].period_utc.isoformat(),
        },
        "metrics": {
            "mae_mw": _decimal_text(mae_mw),
            "rmse_mw": _decimal_text(rmse_mw),
            "mape_percent": _decimal_text(mape_percent),
        },
    }
    artifact_path.write_text(
        json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with validation_path.open("w", newline="", encoding="utf-8") as validation_file:
        writer = csv.DictWriter(
            validation_file,
            fieldnames=(
                "period_utc",
                "actual_demand_mw",
                "predicted_demand_mw",
                "absolute_error_mw",
            ),
        )
        writer.writeheader()
        for example, prediction in validation_predictions:
            writer.writerow(
                {
                    "period_utc": example.period_utc.isoformat(),
                    "actual_demand_mw": _decimal_text(_metric_decimal(example.target_demand_mw)),
                    "predicted_demand_mw": _decimal_text(_metric_decimal(prediction)),
                    "absolute_error_mw": _decimal_text(
                        _metric_decimal(abs(prediction - example.target_demand_mw))
                    ),
                }
            )


def _activate_model(*, session: Session, city_id: UUID, model: ModelVersion) -> None:
    active_models = session.scalars(
        select(ModelVersion).where(
            ModelVersion.city_id == city_id, ModelVersion.is_active.is_(True)
        )
    ).all()
    for active_model in active_models:
        if active_model.id != model.id:
            active_model.is_active = False
            active_model.activated_at = None
    model.is_active = True
    model.activated_at = datetime.now(UTC)


def _training_result(model: ModelVersion, *, reused_existing_version: bool) -> ModelTrainingResult:
    return ModelTrainingResult(
        version=model.version,
        algorithm=model.algorithm,
        source_dataset_version=model.source_dataset_version,
        training_row_count=model.training_row_count,
        validation_row_count=model.validation_row_count,
        mae_mw=Decimal(model.mae_mw),
        rmse_mw=Decimal(model.rmse_mw),
        mape_percent=Decimal(model.mape_percent) if model.mape_percent is not None else None,
        artifact_path=Path(model.artifact_path),
        validation_predictions_path=Path(model.validation_predictions_path),
        reused_existing_version=reused_existing_version,
    )


def _summary(model: ModelVersion) -> ActiveModelSummary:
    return ActiveModelSummary(
        version=model.version,
        algorithm=model.algorithm,
        source_dataset_version=model.source_dataset_version,
        feature_schema_version=model.feature_schema_version,
        quality_policy=model.quality_policy,
        feature_columns=list(model.feature_columns),
        trained_from=model.trained_from,
        trained_to=model.trained_to,
        training_row_count=model.training_row_count,
        validation_row_count=model.validation_row_count,
        mae_mw=Decimal(model.mae_mw),
        rmse_mw=Decimal(model.rmse_mw),
        mape_percent=Decimal(model.mape_percent) if model.mape_percent is not None else None,
        activated_at=model.activated_at,
    )


def _get_demo_city(*, session: Session, settings: Settings) -> City:
    city = session.scalar(
        select(City).where(City.name == settings.demo_city_name, City.country_code == "US")
    )
    if city is None:
        raise ModelNotAvailableError(
            "The configured demo city is missing. Seed the city before model work."
        )
    return city


def _get_active_model(*, session: Session, city_id: UUID) -> ModelVersion:
    model = session.scalar(
        select(ModelVersion)
        .where(ModelVersion.city_id == city_id, ModelVersion.is_active.is_(True))
        .order_by(ModelVersion.activated_at.desc())
    )
    if model is None:
        raise ModelNotAvailableError(
            "No active baseline model exists. Run scripts/train_model.py first."
        )
    return model


def _load_artifact(*, model: ModelVersion, settings: Settings) -> dict[str, Any]:
    base_dir = Path(settings.model_artifact_dir).resolve()
    artifact_path = Path(model.artifact_path).resolve()
    if not artifact_path.is_relative_to(base_dir):
        raise ModelArtifactError("The active model artifact path is outside MODEL_ARTIFACT_DIR.")
    try:
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModelArtifactError("The active model artifact is unavailable or unreadable.") from exc
    if (
        artifact.get("version") != model.version
        or artifact.get("algorithm") != model.algorithm
        or artifact.get("feature_columns") != list(FEATURE_COLUMNS)
        or len(artifact.get("coefficients", [])) != len(FEATURE_COLUMNS)
    ):
        raise ModelArtifactError(
            "The active model artifact does not match its stored model metadata."
        )
    try:
        parameters = np.asarray(
            [artifact["intercept"], *artifact["coefficients"]],
            dtype=float,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ModelArtifactError(
            "The active model artifact has invalid regression parameters."
        ) from exc
    if not np.all(np.isfinite(parameters)):
        raise ModelArtifactError("The active model artifact has non-finite regression parameters.")
    return artifact


def _next_usable_forecast_inputs(
    *,
    session: Session,
    city: City,
    settings: Settings,
) -> tuple[datetime, tuple[float, ...], dict[str, Decimal | str]]:
    latest_demand = session.scalar(
        select(func.max(DemandObservation.period_utc)).where(DemandObservation.city_id == city.id)
    )
    if latest_demand is None:
        raise ForecastInputError("No stored demand history exists for forecast lag features.")
    candidates = session.scalars(
        select(ZoneTemperatureObservation.observed_for)
        .distinct()
        .join(Zone, ZoneTemperatureObservation.zone_id == Zone.id)
        .where(
            Zone.city_id == city.id,
            Zone.active.is_(True),
            ZoneTemperatureObservation.observed_for > _ensure_utc(latest_demand),
        )
        .order_by(ZoneTemperatureObservation.observed_for)
    ).all()
    if not candidates:
        raise ForecastInputError(
            "No future zone-temperature observation is available after the latest stored demand."
        )
    last_input_error: ForecastInputError | None = None
    for candidate in candidates:
        candidate_time = _ensure_utc(candidate)
        try:
            feature_values, inputs = _forecast_features(
                session=session,
                city=city,
                forecast_for=candidate_time,
                settings=settings,
            )
        except ForecastInputError as exc:
            last_input_error = exc
            continue
        return candidate_time, feature_values, inputs
    if last_input_error is not None:
        raise ForecastInputError(
            "No future temperature time has complete coverage and the required "
            "1/24-hour demand lags."
        ) from last_input_error
    raise ForecastInputError("No usable future forecast input is available.")


def _forecast_features(
    *,
    session: Session,
    city: City,
    forecast_for: datetime,
    settings: Settings,
) -> tuple[tuple[float, ...], dict[str, Decimal | str]]:
    lag_one = session.scalar(
        select(DemandObservation.demand_mw).where(
            DemandObservation.city_id == city.id,
            DemandObservation.period_utc == forecast_for - timedelta(hours=1),
            DemandObservation.is_actual.is_(True),
        )
    )
    lag_day = session.scalar(
        select(DemandObservation.demand_mw).where(
            DemandObservation.city_id == city.id,
            DemandObservation.period_utc == forecast_for - timedelta(hours=24),
            DemandObservation.is_actual.is_(True),
        )
    )
    if lag_one is None or lag_day is None:
        raise ForecastInputError(
            "Forecast requires actual demand observations exactly 1 and 24 hours earlier."
        )

    zones = session.scalars(
        select(Zone).where(Zone.city_id == city.id, Zone.active.is_(True)).order_by(Zone.code)
    ).all()
    if not zones:
        raise ForecastInputError("Forecast requires active city zones.")
    zone_weights = {zone.id: Decimal(zone.allocation_weight) for zone in zones}
    observations = session.scalars(
        select(ZoneTemperatureObservation)
        .join(Zone, ZoneTemperatureObservation.zone_id == Zone.id)
        .where(
            Zone.city_id == city.id,
            Zone.active.is_(True),
            ZoneTemperatureObservation.observed_for == forecast_for,
        )
        .order_by(ZoneTemperatureObservation.source_retrieved_at.desc())
    ).all()
    latest_by_zone: dict[UUID, ZoneTemperatureObservation] = {}
    for observation in observations:
        latest_by_zone.setdefault(observation.zone_id, observation)
    usable = {
        zone_id: observation
        for zone_id, observation in latest_by_zone.items()
        if observation.data_status == "available" and observation.mean_c is not None
    }
    if len(usable) != len(zone_weights):
        raise ForecastInputError(
            "Forecast requires complete same-time zone-temperature coverage; "
            "partial/missing inputs are blocked."
        )
    total_weight = sum(zone_weights.values(), start=Decimal("0"))
    if total_weight <= 0:
        raise ForecastInputError("Forecast requires positive active-zone allocation weights.")
    weighted_temperature = (
        sum(
            (
                Decimal(observation.mean_c) * zone_weights[zone_id]
                for zone_id, observation in usable.items()
            ),
            start=Decimal("0"),
        )
        / total_weight
    )
    city_temperature = weighted_temperature.quantize(METRIC_SCALE, rounding=ROUND_HALF_UP)
    cooling_degree_hours = max(
        Decimal("0"), city_temperature - settings.cooling_base_temperature_c
    ).quantize(METRIC_SCALE, rounding=ROUND_HALF_UP)
    local_time = forecast_for.astimezone(_timezone(settings.demo_timezone))
    forecast_flags = {observation.is_forecast for observation in usable.values()}
    source_kind = (
        "forecast"
        if forecast_flags == {True}
        else "actual"
        if forecast_flags == {False}
        else "mixed"
    )
    features = (
        float(cooling_degree_hours),
        float(local_time.hour),
        float(local_time.weekday()),
        float(local_time.weekday() >= 5),
        float(local_time.month),
        float(local_time.date() in _us_federal_holidays(local_time.year)),
        float(lag_one),
        float(lag_day),
    )
    return features, {
        "city_temperature_c": city_temperature,
        "cooling_degree_hours": cooling_degree_hours,
        "temperature_source_kind": source_kind,
        "lag_demand_1h_mw": Decimal(lag_one),
        "lag_demand_24h_mw": Decimal(lag_day),
    }


def _timezone(value: str) -> ZoneInfo:
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ForecastInputError("DEMO_TIMEZONE must be a valid IANA timezone.") from exc


def _required(record: dict[str, str | None], field: str) -> str:
    value = record.get(field)
    if value is None or not value.strip():
        raise ValueError(f"{field} is required")
    return value


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValueError("boolean values must be true or false")


def _parse_int(record: dict[str, str | None], field: str, *, minimum: int, maximum: int) -> int:
    value = int(_required(record, field))
    if not minimum <= value <= maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}")
    return value


def _ensure_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _metric_decimal(value: float) -> Decimal:
    if not np.isfinite(value):
        raise ModelTrainingError("A model calculation produced a non-finite result.")
    return Decimal(str(value)).quantize(METRIC_SCALE, rounding=ROUND_HALF_UP)


def _decimal_text(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None
