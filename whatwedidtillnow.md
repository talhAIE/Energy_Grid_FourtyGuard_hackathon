# What We Did Till Now

This file tracks completed work and how it was implemented. Update it at the end of every implementation phase.

## Project decisions

- **Project:** Energy Grid Heat-Demand Forecaster.
- **Demo location:** Houston, Texas, using ERCOT data for real historical grid-demand calibration.
- **Core data:** FortyGuard heatmaps for temperature and EIA/ERCOT sources for historical demand.
- **Safety boundary:** recommendations only; never direct control of electric-grid equipment.
- **Backend stack:** Python 3.12, FastAPI, PostgreSQL/PostGIS, SQLAlchemy, Alembic, NumPy-backed transparent
  baseline regression, and client-triggered provider polling (no Redis/Celery worker).

## Documentation completed

| File | What it contains |
| --- | --- |
| `EnergyGrid.md` | Product idea, inputs/outputs, forecasting logic, architecture, stack, demo scope, and pitch |
| `apifourtygaurd.md` | FortyGuard API endpoints, asynchronous job flow, constraints, security, and project usage strategy |
| `backendIMPLEMENTATION.md` | 14 short backend implementation phases, definitions of done, and manual QA instructions |

## Implementation progress

| Phase | Status | What was done |
| --- | --- | --- |
| 0 - Foundation | Complete | Created FastAPI project, virtual environment, safe config template, `/api/v1/health`, optional Docker files, linting, and local setup guide |
| 1 - Database foundation | Implemented; manual database QA pending | Added PostGIS Docker configuration, SQLAlchemy models, Alembic setup, initial core-schema migration, database health check, and idempotent city seed script |
| 2 - Zone management | Implemented; manual database QA pending | Added Houston zone seed data, GeoJSON validation, zone API, allocation/overlap/boundary checks, and audit events |
| 3 - EIA ingestion | Implemented; manual live-data QA pending | Configurable EIA/ERCOT hourly demand import, normalized storage, duplicate protection, API routes, and audit trail |
| 4 - FortyGuard jobs | Implemented; manual live-provider QA pending | Validated, idempotent FortyGuard heatmap submission with persisted jobs/runs and audit trail |
| 5 - API-triggered polling | Implemented; manual live-provider QA pending | One-shot status polling, durable job state, controlled provider response storage, and job-state API |
| 6 - Heatmap normalization | Implemented; manual live-provider QA pending | Automatic tile parsing, centroid-based zone aggregation, missing-zone markers, and temperature timeline API |
| 7 - Feature dataset | Implemented; manual dataset QA pending | Versioned CSV/quality report, UTC/local time alignment, Cooling Degree Hours, calendar features, and explicit missing-temperature labels |
| 8 - Baseline demand model | Implemented; manual model/database QA pending | Chronological OLS training, stored metrics/model versions, JSON artifact, validation export, and safeguarded city forecast API |
| 9-13 | Not started | Zone risk, recommendations, scheduler, replay mode, and QA pack |

## Phase 0 - Foundation details

### How it was implemented

- Created `backend/` as a standalone Python 3.12 FastAPI service.
- Added `backend/.env.example`; real credentials belong only in ignored `backend/.env`.
- Added `GET /api/v1/health`, which returns non-sensitive service status.
- Created a local `.venv` and installed FastAPI, Uvicorn, Pydantic settings, and Ruff.
- Added `backend/README.md` with local start instructions.

### Verification performed

- Ruff lint: passed.
- App import and health response: passed.

## Phase 1 - Database foundation details

### How it was implemented

- Added SQLAlchemy, Alembic, Psycopg, and GeoAlchemy2 dependencies.
- Added Postgres/PostGIS service to Docker Compose, including a database health check and persistent local volume.
- Added a lazy database engine and safe `database` health state: `healthy`, `unavailable`, or `not_configured`.
- Added Alembic configuration and initial migration `20260827_0001`.
- The initial migration enables PostGIS then creates:
  - `cities`
  - `zones`
  - `integration_jobs`
  - `audit_events`
- Added SQLAlchemy models matching the Phase 1 schema.
- Added `python -m app.scripts.seed_city`, which creates Houston, Texas once and does not duplicate it.

### Manual QA still required

Docker Desktop or another running Postgres/PostGIS instance is required to run these checks:

1. In `backend/`, copy `.env.example` to `.env` if it does not already exist.
2. Start PostGIS and API: `docker compose up --build -d`.
3. Run migration: `docker compose exec api alembic upgrade head`.
4. Seed Houston: `docker compose exec api python -m app.scripts.seed_city`.
5. Call `GET /api/v1/health`; expected value: `dependencies.database = "healthy"`.
6. Run the seed command again; expected result: no duplicate city.

## Phase 2 - Zone management details

### How it was implemented

- Added eight version-controlled Houston demo zones and an approximate demo analysis boundary under `backend/app/data/seed/`.
- Added Shapely-based GeoJSON validation for Polygon/MultiPolygon geometry, closed rings, coordinate ranges, and invalid/self-intersecting shapes.
- Added a development-only zone API:
  - `GET /api/v1/zones`
  - `POST /api/v1/zones`
- Zone creation verifies that a zone is inside the demo boundary, uses a unique code, does not overlap an existing zone, and keeps active allocation weights at or below `1.0`.
- Added `python -m app.scripts.seed_zones` to load the eight zones only once.
- Added an append-only `zone.created` audit event for every successfully created zone.
- Updated the city seed to attach the project’s approximate Houston demo boundary when it is missing.

### Verification performed

- Static lint: passed.
- Houston seed data: eight valid zones, all inside the demo boundary, no overlap, allocation weights total exactly `1.0`.
- FastAPI application imports with `/api/v1/zones` registered.

### Manual QA still required

After Phase 1 database QA is available:

1. Run `docker compose exec api python -m app.scripts.seed_city`.
2. Run `docker compose exec api python -m app.scripts.seed_zones`.
3. Call `GET /api/v1/zones`; expected result: eight active zones.
4. Run the zone seed command again; expected result: `Created 0 zone(s).`
5. Create a valid non-overlapping development zone; confirm a `201` response and `zone.created` audit event.
6. Try an unclosed polygon, an outside-boundary polygon, a duplicate code, and an overlapping polygon; confirm each is rejected.
7. Try adding a zone that makes active allocation weights exceed `1.0`; confirm it is rejected.

## Phase 3 - EIA demand-data ingestion details

### How it was implemented

- Added the `demand_observations` database model and Alembic migration `20260827_0002`.
  Each observation stores the city, UTC timestamp, data source, source-area code, demand in MW,
  actual/forecast indicator, optional quality flag, and standard audit timestamps.
- Added a database uniqueness rule for `city + source + source area + UTC timestamp`. Re-importing
  the same EIA period skips existing observations instead of creating duplicates.
- Added safe, configuration-driven EIA settings to `backend/.env.example`:
  `EIA_DEMAND_ROUTE`, `EIA_DEMAND_AREA_CODE`, `EIA_DEMAND_TYPE`, timezone, request timeout, and a
  maximum import range. The default is EIA Form 930 hourly ERCOT (`ERCO`) demand; no API key is in code.
- Added `app/services/eia_client.py`, which uses an explicit HTTP timeout, paginates EIA responses,
  validates/normalizes timestamps to UTC, validates MW values, and turns provider/configuration
  failures into safe messages without exposing the API key.
- Added `app/services/demand_data_service.py`, which fetches a bounded historical range, persists only
  unseen observations, records a `demand.eia_imported` audit event, and lists stored observations.
- Added two backend routes:
  - `POST /api/v1/data/eia/import` imports a maximum 31-day historical range for the configured EIA area.
  - `GET /api/v1/data/demand?start=...&end=...` returns only the stored, chronological demand records.
- Added the command-line helper:
  `python -m app.scripts.import_eia_data --start <ISO-8601> --end <ISO-8601>`.
- Added `httpx` as the project HTTP dependency and documented the Phase 3 setup/use flow in
  `backend/README.md`.

### Verification performed

- Static lint and Python compilation: passed.
- FastAPI OpenAPI validation: both new demand routes are registered.
- Demand model metadata validation: the table and source-area-timestamp uniqueness rule are registered.
- EIA normalizer checked with a representative EIA Form 930-style demand record: it produces a UTC
  timestamp, MW decimal value, actual flag, and deduplicated result.
- Alembic migration graph validation: `20260827_0002` correctly follows the Phase 1 core schema migration.

### Manual QA still required

This needs Docker Desktop or another running Postgres/PostGIS database, plus your local `EIA_API_KEY` in
`backend/.env`. Do not paste the key into chat or commit it.

1. From `backend/`, ensure the EIA variables from `.env.example` exist in `backend/.env`; keep the default
   `EIA_DEMAND_AREA_CODE=ERCO` for this Houston/ERCOT demo.
2. Run `docker compose up --build -d`, then `docker compose exec api alembic upgrade head`.
3. Run `docker compose exec api python -m app.scripts.seed_city`.
4. Import one hot historical week:
   `docker compose exec api python -m app.scripts.import_eia_data --start 2025-08-01T00:00:00Z --end 2025-08-08T00:00:00Z`.
5. In `/docs`, call `GET /api/v1/data/demand` for the same start/end. Confirm records are chronological,
   use `period_utc`, show `source: "EIA"`, `source_area_code: "ERCO"`, `is_actual: true`, and a positive
   `demand_mw` value.
6. Compare several timestamps and MW values with the EIA data browser for the ERCOT hourly demand series.
7. Run the identical import again. Expected: `created=0` and the stored record count does not grow.
8. Submit an end before start, or a range longer than 31 days, to `POST /api/v1/data/eia/import`. Expected:
   a clear `422` response with `invalid_date_range`.
9. Temporarily leave `EIA_API_KEY` blank only in your local `backend/.env`, restart the API, and import again.
   Expected: a clear `503` response with `eia_not_configured`; restore the key afterward.

## Phase 4 - FortyGuard heatmap submission details

### How it was implemented

- Added configurable FortyGuard settings to `backend/.env.example`: base URL, server-side API key,
  request timeout, default granularity, maximum heatmap AOI area, and 12-hour forecast-window limit.
  The key is never returned, logged, or stored in database fields.
- Added `app/services/fortyguard_client.py`, which isolates request construction and sends only the
  documented `api-key` header to `POST /v1/heatmap`. It accepts a successful response only when it
  contains a non-empty `data.activity_id` and turns provider failures into safe error messages.
- Added strict heatmap request validation:
  - one closed GeoJSON Polygon inside a FeatureCollection;
  - a supported U.S. envelope and containment within the selected Houston demo boundary;
  - a locally calculated area at or below the configured plan limit;
  - valid filter-dependent date/time fields, dates from 2019-01-01 onward, and the configured
    future limit;
  - granularity only `60`, `80`, or `100` metres; and analytic type only `tcm` for this MVP.
- Added `heatmap_runs` model and Alembic migration `20260827_0003`. It saves safe request context:
  internal job ID, UTC requested time, granularity, analytic type, AOI geometry, date-time filter,
  and source kind. It does not store API keys or provider headers.
- Added `POST /api/v1/heatmaps/submit`. It reserves an internal `integration_jobs` row with a canonical
  SHA-256 request hash before calling FortyGuard, then stores the returned `activity_id` and returns
  HTTP `202`. The HTTP request waits only for submission acknowledgement, never for final map results.
- An identical request returns the existing active/completed job with `reused: true`, preventing a
  duplicate paid submission. A provider timeout or uncertain failure is deliberately not retried.
- Added audit events for submission start, successful submission, provider submission failure, and
  service-level validation failure.
- Updated `backend/README.md` with an exact small-AOI manual request and expected results.

### Verification performed

- Static lint and Python compilation: passed.
- FastAPI OpenAPI validation: `POST /api/v1/heatmaps/submit` is registered.
- Heatmap request schema and GeoJSON validation: passed with a small Houston-area Polygon; the provider
  payload strips unneeded caller properties and calculates its area.
- Canonical request hashing: semantically identical payloads produce the same hash.
- Heatmap-run model metadata validation: the one-run-per-job uniqueness rule is registered.
- Alembic migration graph validation: `20260827_0003` correctly follows the EIA migration chain.

### Manual QA still required

This requires a running PostGIS database and your local `FORTYGUARD_API_KEY` in `backend/.env`. Do not
paste the key into chat or commit it. The task is charged only on successful provider completion, so use
the small AOI below and do not repeatedly vary it during a test.

1. From `backend/`, set the FortyGuard variables listed in `.env.example`. Keep
   `FORTYGUARD_MAX_HEATMAP_AREA_SQ_MI=50` only if it matches the plan attached to your key.
2. Run `docker compose up --build -d`, then `docker compose exec api alembic upgrade head` and
   `docker compose exec api python -m app.scripts.seed_city`.
3. In `/docs`, call `POST /api/v1/heatmaps/submit` using the small Houston FeatureCollection in
   `backend/README.md`, granularity `80` or `100`, and analytic type `tcm`.
4. Expected: HTTP `202`, a non-empty internal `job_id`, `status: "submitted"`, and non-empty
   `activity_id`. Confirm no key appears in the response or logs.
5. Submit exactly the same body again. Expected: the original IDs and `reused: true`; the audit trail
   must not show a second provider submission.
6. Submit an unclosed polygon, a polygon outside the Houston demo boundary, `granularity: 70`, or
   analytic type other than `tcm`. Expected: `400 invalid_heatmap_request`, no `activity_id`, and a
   `heatmap.validation_failed` audit event for service-level failures.
7. Temporarily remove only `FORTYGUARD_API_KEY` from local `backend/.env` and restart the API. Submit
   a valid request. Expected: `503 fortyguard_not_configured`; restore the key afterward.

### Known boundary for the next phase

- Phase 4 deliberately stops after submission acknowledgement. It does not poll `/v1/status/{activity_id}`
  and does not expose a job-status endpoint yet. Phase 5 adds client-triggered one-shot polling,
  transient-404 handling, terminal status updates, and controlled result capture without Redis/Celery.

## Phase 5 - API-triggered polling and raw-result capture details

### How it was implemented

- Followed the current implementation plan's client-triggered approach: Phase 5 uses no Redis queue or
  Celery worker. Every `POST /api/v1/jobs/{job_id}/poll` call performs one FortyGuard status request,
  persists the outcome, and returns without waiting for task completion.
- Added `GET /api/v1/jobs/{job_id}` for safe persisted job state and
  `POST /api/v1/jobs/{job_id}/poll` for one-shot polling. Both expose only safe metadata such as status,
  activity ID, timestamps, poll count, error code, and raw-response availability.
- Extended `integration_jobs` with `provider_status`, `poll_attempts`, `last_polled_at`, and controlled
  `raw_response_json`; migration `20260827_0004` adds the fields and provider-status index.
- Extended the isolated FortyGuard client with `GET /v1/status/{activity_id}`. It recognizes the initial
  `404` as transient and returns no raw provider body for that case. It recognizes provider terminal
  statuses case-insensitively: `completed`/`succeeded` and `failed`/`error`.
- Added a hard polling deadline based on `requested_at` and `FORTYGUARD_MAX_POLL_SECONDS`. The next poll
  after the deadline changes the internal job to `timed_out` with `poll_window_exceeded`.
- Stored provider responses only after recursively redacting API-key/token/secret/signature/download/URL
  fields, limiting list entries and nesting, and enforcing `FORTYGUARD_MAX_RAW_RESPONSE_BYTES`. Oversized
  payloads are replaced by a hash-and-size summary. Raw content is never returned by the job APIs.
- Added audit events for completed, failed, timed-out, and temporarily unavailable polls. A short-lived
  404 remains `processing` so the dashboard or QA can safely make the next short poll.
- Updated `backend/README.md` with the API polling procedure. The older Phase 4 boundary is superseded:
  job-status routes and one-shot polling are now implemented.

### Verification performed

- Static lint and Python compilation: passed.
- FastAPI OpenAPI validation: both job routes are registered.
- Mocked FortyGuard status response: provider status parsing passed without a live API call.
- Controlled response validation: API-key and signed-URL fields are redacted; large lists are limited.
- Integration-job model metadata validation: the four polling fields are registered.
- Alembic migration graph validation: `20260827_0004` correctly follows the heatmap-run migration.

### Manual QA still required

This requires PostGIS and your local `FORTYGUARD_API_KEY` in `backend/.env`; Redis and a Celery worker are
not required for this phase. Do not paste the key into chat or commit it.

1. Start the API with its PostGIS database connection, then run
   `docker compose exec api alembic upgrade head` (or the equivalent command for your configured database).
2. Submit the small valid Houston heatmap request from `backend/README.md`; keep its returned `job_id`.
3. Call `POST /api/v1/jobs/{job_id}/poll` every five seconds until `status` is terminal. Each call should
   return promptly, never hold open to wait for completion.
4. Between polls call `GET /api/v1/jobs/{job_id}`. Confirm activity ID, provider status, poll attempt
   count, last-poll time, and final completion time persist across requests.
5. Restart the API while the job is still `processing`. Continue manual polls afterward; confirm the same
   job state is recovered and no second submission occurs.
6. If the first status poll gets a provider `404`, expect internal `status: "processing"` and
   `provider_status: "not_found"`. Wait five seconds and poll again instead of treating it as a failure.
7. Reduce `FORTYGUARD_MAX_POLL_SECONDS` temporarily in local configuration, submit a job, wait past that
   limit, then poll once. Expected: `status: "timed_out"` and `error_code: "poll_window_exceeded"`.
8. Confirm `GET /api/v1/jobs/{job_id}` never exposes `raw_response_json`, signed URLs, provider headers,
   or either API key.

### Known boundary for the next phase

- Resolved in Phase 6: completed heatmap `map_data` is now parsed and aggregated into zone observations.

## Phase 6 - Heatmap normalization and zone aggregation details

### How it was implemented

- Added `zone_temperature_observations` and migration `20260827_0005`. Each observation records the zone,
  heatmap requested time, mean/min/max/standard-deviation Celsius values, tile count, source heatmap run,
  forecast flag, data status, and source-retrieval time.
- Added a `zone_id + source_run_id` uniqueness rule, so a completed heatmap run cannot generate duplicate
  temperature records when a status check is repeated.
- Added strict extraction of FortyGuard `data.result.map_data`: it must be a GeoJSON FeatureCollection of
  valid Polygon/MultiPolygon Features with a supported Celsius property. The parser accepts common provider
  value names (`temperature_c`, `temperature`, `temp_c`, `temp`, `tcm`, or `value`) and rejects missing,
  non-numeric, or non-finite temperatures.
- Added automatic aggregation during the first successful completed/succeeded job poll. It uses the live
  in-memory provider response before Phase 5's controlled raw-response summary can truncate a large map.
- Chose and documented **tile-centroid assignment**: one tile goes to the active zone that covers its
  centroid. A code-order tie-break handles a centroid on a shared zone boundary. This prevents the same tile
  from contributing to two zones.
- For every active zone whose area overlaps the heatmap AOI, the service persists either calculated
  population statistics or a `missing` marker with null statistics and tile count zero. If the AOI overlaps
  no zones, it creates no observations and writes a `heatmap.normalized_no_overlap` audit event.
- Added `GET /api/v1/temperatures?start=...&end=...`, with optional `zone_id` and `include_missing` filters.
  The response exposes only normalized observations, never the raw provider map.
- Added audit records for successful normalization, no-overlap handling, and safe normalization failures.

### Verification performed

- Static lint and Python compilation: passed.
- FastAPI OpenAPI validation: the temperature timeline route is registered.
- Representative tile GeoJSON parsing: two Celsius tiles produced correct mean `32.000`, min `30.000`,
  max `34.000`, and population standard deviation `2.000`.
- Zone-temperature model metadata validation: required traceability fields and the one-zone-per-run
  uniqueness rule are registered.
- Alembic migration graph validation: `20260827_0005` correctly follows the polling migration.

### Manual QA still required

This requires PostGIS, seeded active zones, and a completed FortyGuard heatmap job. Do not paste the API key
into chat or commit it.

1. Run `docker compose exec api alembic upgrade head`, then seed the city and zones if needed with
   `python -m app.scripts.seed_city` and `python -m app.scripts.seed_zones` inside the API container.
2. Submit a valid `tcm` heatmap whose AOI overlaps one or more active demo zones, then poll it to
   `status: "completed"` using the Phase 5 route.
3. Query `GET /api/v1/temperatures` for the requested UTC time window. Confirm every active zone overlapping
   that AOI has one record with `source_run_id`, `source_retrieved_at`, and the correct `is_forecast` value.
4. For available records, compare the returned mean/min/max values with a visually plausible portion of the
   provider heatmap and verify `tile_count > 0`.
5. For a zone overlapping the AOI but receiving no tile centroid, confirm `data_status: "missing"`, zero tile
   count, and null statistics. It must not contain a numeric zero temperature.
6. Submit a small heatmap AOI that overlaps no active zone. After completion, confirm the temperature query
   returns zero records for that run/time and the audit history contains `heatmap.normalized_no_overlap`.
7. Repeat a status poll for an already completed job. Confirm no duplicate observations are created for the
   same `source_run_id`.

### Known boundary for the next phase

- Resolved in Phase 7: EIA demand and zone temperatures are now aligned into a documented, versioned feature
  dataset with Cooling Degree Hours and visible quality states.

## Phase 7 - Data preparation and Cooling Degree Hours details

### How it was implemented

- Added `app/services/feature_dataset_service.py`, which builds one model-ready row for each persisted EIA
  demand observation in a requested UTC range. It matches only zone-temperature observations at the **same
  UTC timestamp**; it never forward-fills or interpolates values.
- Added allocation-weighted city temperature. With all active zones available, the row is `complete`. With
  only some zones available, it keeps the available-zone weighted mean but marks the row
  `partial_temperature` and records the represented allocation weight. With no usable temperatures, both
  temperature and CDH are null and the row is `missing_temperature`.
- Added configurable Cooling Degree Hours using
  `max(0, city_temperature_c - COOLING_BASE_TEMPERATURE_C)`. The default city baseline is 18 Celsius.
- Added local calendar fields from the same UTC instant in `DEMO_TIMEZONE`: local hour, day of week, weekend,
  month, and an observed U.S. federal-holiday flag. UTC is retained beside the local time so daylight-saving
  transitions remain traceable.
- Added `python -m app.scripts.build_feature_dataset --start <ISO-8601> --end <ISO-8601>` and safe
  configuration for its maximum range and generated-artifact directory. The script writes a versioned CSV
  and matching JSON quality report; output under `app/data/generated/` is ignored by Git.
- Dataset versions are a SHA-256 fingerprint of the schema version, city, requested time range, cooling
  baseline, and source-derived feature rows. Rebuilding unchanged source data produces the same artifact
  name.
- Added `docs/feature-dataset-contract.md` and Phase 7 operating/manual-QA instructions to the backend
  README. The contract defines the complete row schema and quality policy for Phase 8.
- Added an append-only `feature_dataset.built` audit event after the output artifacts are written. No
  database migration or public API route was needed for this phase.

### Verification performed

- Static lint and Python compilation: passed.
- Feature-building helper checks cover complete, partial, and missing temperature coverage; CDH uses the
  configured baseline and preserves nulls for missing temperature data.
- Local-time conversion and observed U.S. federal-holiday feature checks were performed, including a Houston
  daylight-saving-time timestamp.
- Command-line help and generated-artifact contract were checked without contacting EIA or FortyGuard.

### Manual QA still required

This requires the previous phase database/manual QA: an active PostGIS database, seeded city/zones, stored
EIA demand, and normalized zone temperatures. Do not paste either API key into chat or commit `backend/.env`.

1. Follow Phase 1, 3, and 6 manual setup to seed active zones, import a historical ERCOT demand range, and
   complete/poll a FortyGuard heatmap for matching UTC times.
2. From `backend/`, run
   `python -m app.scripts.build_feature_dataset --start 2025-08-01T00:00:00Z --end 2025-08-08T00:00:00Z`.
   The requested interval must contain at least one stored demand observation and cannot exceed the
   configured `FEATURE_DATASET_MAX_RANGE_DAYS`.
3. Open the emitted CSV and JSON report. Confirm every row includes UTC/local timestamps, target demand MW,
   feature quality status, coverage, and calendar values. Confirm the JSON report's row and quality counts
   agree with the CSV.
4. With `COOLING_BASE_TEMPERATURE_C=18`, verify five available-temperature rows or controlled records:
   16, 18, 20, 25, and 30 Celsius must yield CDH 0, 0, 2, 7, and 12 respectively.
5. Inspect records around a Houston daylight-saving-time change. Confirm `period_utc` stays unique and
   `period_local` represents the correct local offset/hour; do not merge the repeated local fall-back hour.
6. Build a range with only partial zone coverage. Confirm it is labeled `partial_temperature`, displays its
   coverage weight, and uses only the available zones. Build or inspect a range with no usable zone
   temperatures; confirm temperature and CDH are null and the status is `missing_temperature`.
7. Run the identical command again without changing stored inputs or configuration. Confirm the dataset
   version/artifact names are identical. Change only `COOLING_BASE_TEMPERATURE_C`, rebuild, and confirm the
   version and CDH values change.

### Known boundary for the next phase

- Resolved in Phase 8: an explicit active city-level baseline model can be trained chronologically and used for
  a clearly labeled demand estimate when all required inputs are present.

## Phase 8 - Baseline demand forecast model details

### How it was implemented

- Added `model_versions` and Alembic migration `20260827_0006`. Each record stores the city, deterministic
  model version, algorithm, source dataset SHA-256, training/validation periods and row counts, MAE/RMSE/MAPE,
  artifact paths, feature metadata, and explicit active state.
- Added a transparent NumPy ordinary least-squares model. The JSON artifact contains the intercept and ordered
  coefficients for Cooling Degree Hours, local calendar fields, and 1-hour/24-hour lagged demand; it is not an
  opaque pickled model.
- Added `python -m app.scripts.train_model --dataset <Phase-7-CSV>`. It validates the CSV contract, accepts
  only actual-demand rows with `complete` temperature coverage and usable CDH/lags, and preserves chronological
  order. No missing input is interpolated or treated as zero.
- Added a configurable chronological holdout split (80% training / 20% validation by default), a 72-row minimum
  training guard, and MAE/RMSE/MAPE calculation. The latest validation period is never shuffled into training.
- Training writes a versioned JSON artifact and a validation CSV containing timestamp, actual MW, predicted MW,
  and absolute error. Both live under the ignored generated-data directory for manual charting/review.
- Added one explicit active model per city. Training activates the new version and deactivates prior versions;
  repeating unchanged training input reuses the deterministic stored version instead of creating a duplicate.
- Added forecast API routes:
  - `GET /api/v1/forecast/models/active` returns active-model metadata and validation metrics.
  - `POST /api/v1/forecast/run` estimates city/grid-area demand for a requested or next usable temperature time.
- The forecast route requires a readable active artifact, actual demand exactly one and 24 hours earlier, and
  complete same-time temperature coverage for every active zone. It rejects missing/partial inputs visibly and
  returns `estimate_type: "estimate"`; it does not create zone risk, allocate zone demand, or control equipment.
- Added `docs/baseline-model-contract.md`, Phase 8 configuration examples, operating steps, and manual QA
  guidance. Added NumPy as an explicit runtime dependency.

### Verification performed

- Static lint and Python compilation: passed.
- Synthetic chronological CSV check: 150 hourly rows generated 100 training and 25 validation examples after
  the 1-hour/24-hour lag and incomplete-temperature exclusion rules. Ordinary least-squares fitting, prediction,
  MAE/RMSE/MAPE, and deterministic version generation passed.
- FastAPI OpenAPI validation: `GET /api/v1/forecast/models/active` and `POST /api/v1/forecast/run` are
  registered.
- Training command help was checked. No live EIA, FortyGuard, database migration, artifact write, or forecast
  was run because the required PostGIS data/manual-QA setup is not yet available.

### Manual QA still required

This requires completed Phase 1, 3, 6, and 7 database/manual QA, including sufficient **complete** historical
feature rows and future/selected temperature coverage. Do not paste API keys into chat or commit `backend/.env`.

1. From `backend/`, install the Phase 8 dependency with `python -m pip install -e ".[dev]"`, then run
   `alembic upgrade head` against the PostGIS database.
2. Build a Phase 7 CSV for a documented historical period. Ensure enough consecutive complete rows remain after
   1-hour/24-hour lags for at least 72 training rows plus validation rows; a week of hourly data is a practical
   minimum for the default setting.
3. Run `python -m app.scripts.train_model --dataset <exact-feature-csv-path>`. Record the printed model version,
   artifact path, validation CSV path, MAE, RMSE, and MAPE.
4. Call `GET /api/v1/forecast/models/active`. Confirm it returns the same version, algorithm, source dataset,
   chronological periods, row counts, and metrics as training output.
5. Open the validation CSV in a spreadsheet and chart/compare actual versus predicted MW. Confirm validation
   timestamps occur strictly after the training period and are not included in the training rows.
6. Call `POST /api/v1/forecast/run` with a selected time that has complete zone temperatures plus actual demand
   at exactly one and 24 hours earlier. Confirm the response is `estimate_type: "estimate"`, contains the active
   model version and predicted MW, and never calls it a measured feeder/zone value.
7. Try a time with partial/missing zone temperatures, a missing lag, and an absent/corrupted local artifact.
   Confirm each returns a readable safe error (`forecast_input_not_ready` or `model_artifact_unavailable`) rather
   than an invented forecast. Restore the artifact afterward.
8. Train the identical CSV again. Confirm it reuses the same deterministic model version. Train a changed
   dataset or configuration and confirm a new model version becomes active while the prior version remains stored.

### Known boundary for the next phase

- Phase 8 produces only a city/grid-area demand estimate. Phase 9 will allocate that estimate to zones as an
  explicitly labeled proxy, calculate deterministic heat/demand risk scores and confidence, and persist zone
  forecast outputs. It must not claim actual feeder demand.

## Secrets reminder

- Do not commit `.env` files.
- Do not paste either API key in chat or source code.
- The local backend file must use these exact names:
  - `EIA_API_KEY=...`
  - `FORTYGUARD_API_KEY=...`
