# Baseline Demand Model Contract

## Scope

Phase 8 trains a transparent **city/grid-area demand estimate** for the Houston/ERCOT demo. It is not a
feeder-level measurement and does not allocate demand to zones; that begins in Phase 9.

The model is ordinary least-squares linear regression. Its saved artifact is JSON, so the intercept and every
coefficient can be inspected without loading an opaque binary format.

## Eligible training rows

The trainer reads a Phase 7 CSV and uses only rows that meet all of these rules:

- `target_is_actual` is `true`;
- `feature_quality_status` is `complete`;
- `cooling_degree_hours` is present; and
- actual demand is present at exactly one hour and 24 hours before the target timestamp.

Rows with partial or missing temperatures, absent CDH, non-actual targets, or missing lag demand are excluded.
No values are interpolated or substituted with zero.

## Features and target

| Role | Field |
| --- | --- |
| Target | `target_demand_mw` |
| Heat | `cooling_degree_hours` |
| Calendar | `local_hour`, `local_day_of_week`, `is_weekend`, `local_month`, `is_us_federal_holiday` |
| Demand history | `lag_demand_1h_mw`, `lag_demand_24h_mw` |

The city temperature used for live forecasting is allocation-weighted from active zones, matching Phase 7.

## Split and metrics

Rows remain in UTC chronological order. The earliest 80% train the model and the latest 20% validate it by
default; change only `MODEL_VALIDATION_FRACTION` in local configuration (maximum 50%). The process never
shuffles time-series rows.

The stored validation metrics are:

- `mae_mw`: mean absolute error in MW;
- `rmse_mw`: root mean squared error in MW; and
- `mape_percent`: mean absolute percentage error, excluding zero actual targets.

## Artifact and versioning

`MODEL_ARTIFACT_DIR` defaults to `app/data/generated/models/`, which is ignored by Git. Training writes:

- `<model-version>.json`: algorithm, feature order, intercept, coefficients, source dataset SHA-256, and metrics;
- `<model-version>.validation.csv`: chronological actual/predicted/error rows for manual charting; and
- one `model_versions` database record with model metadata, metrics, source dataset fingerprint, and active state.

The model version is deterministic for the same dataset bytes and validation configuration. One model is marked
active for the city at a time; the forecast API loads that explicit version only.

## Live forecast safety

`POST /api/v1/forecast/run` returns `estimate_type: "estimate"`. It requires the selected time to have:

- an active model and readable matching JSON artifact;
- actual demand exactly one and 24 hours earlier; and
- complete same-time temperature coverage for all active zones.

Partial or missing weather coverage is rejected with a readable `forecast_input_not_ready` response. A negative
linear-regression result is clamped to zero and disclosed through `prediction_was_clamped`.
