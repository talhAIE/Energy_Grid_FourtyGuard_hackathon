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
| 9 - Zone risk forecast | Implemented; manual model/database QA pending | Heat-adjusted proxy zone allocation, persisted explainable risk scores, confidence/freshness signals, and zone forecast APIs |
| 10 - Recommendations and approvals | Implemented; manual model/database QA pending | Guarded recommendations, bounded action catalogue, immutable human decisions, expiry/supersession, and audit trail |
| 11 - Pipeline and safeguards | Implemented; manual live-provider/database QA pending | Durable manually advanced pipeline cycles, one-shot orchestration, idempotency, freshness state, poll limits, and soft submission budget |
| 12 - Replay mode and demo reliability | Implemented; manual database QA pending | Offline 12-hour Houston scenario, protected replay endpoints, persisted standard records, and visible `data_mode` API disclosure |
| 13 - API hardening and QA pack | Implemented; Docker/PostGIS and live-provider QA pending | Stable pagination/error contracts, audit-history API, restrictive CORS, API contract, startup runbook, and end-to-end manual QA pack |

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

- Resolved in Phase 9: city-level estimates are now allocated to zones as explicitly labeled proxy forecasts.

## Phase 9 - Zone demand allocation and risk-scoring details

### How it was implemented

- Added the `zone_forecasts` table and Alembic migration `20260829_0007`. Every record retains the zone,
  forecast time, baseline-model version, city estimate, zone allocation weight, temperature inputs, baseline and
  predicted MW, uplift, risk, confidence, freshness status, and a structured explanation object.
- Updated `POST /api/v1/forecast/run` so that a successful safeguarded city estimate immediately generates one
  zone forecast for every active zone. The city response remains an `estimate`; every zone value is explicitly
  marked `estimate_type: "proxy"` because real feeder/zone demand is not available.
- Zone baseline MW is the city estimate distributed by allocation weight. The proxy allocation adjusts each
  weight with the zone's temperature anomaly versus the allocation-weighted city temperature, then normalizes
  all heat-adjusted weights. This keeps the zone-MW total aligned with the city estimate apart from rounding.
- Added a deterministic, persisted `zone-risk-v1` calculation. It normalizes positive uplift (45%), positive
  heat anomaly (30%), positive one-hour temperature ramp (15%), and uncertainty (10%), then applies a logistic
  score mapping. Labels are `low` 0-39, `watch` 40-64, `high` 65-79, and `critical` 80-100.
- Uncertainty is explicit, never silently filled: spatial temperature variability, a missing exact prior-hour
  temperature, and stale retrieval time increase the penalty. Stale/uncertain outputs lower confidence. Missing
  or partial same-time active-zone coverage blocks zone forecasting instead of inventing an allocation.
- Added `GET /api/v1/forecasts/latest` for the latest all-zone set and
  `GET /api/v1/forecasts/zones/{zone_id}` for a bounded timeline with its structured evidence.
- Added configurable but versioned-in-explanation normalization scales for anomaly, ramp, spatial variability,
  uplift, and maximum source age. The exact values used are retained in every forecast's explanation JSON.
- Added an append-only `zone_forecasts.generated` audit event for each newly persisted set. Re-running the same
  active model and forecast time reuses the existing complete set rather than overwriting historical outputs.

### Verification performed

- Python compilation succeeds for the API, migrations, models, and Phase 9 service.
- The migration follows `20260827_0006_model_versions` and adds foreign keys for both the zone and model version,
  a uniqueness rule for `zone + model + forecast time`, and indexes for latest-set and per-zone timeline reads.
- Static inspection confirmed the city forecast route preserves its existing model/artifact/input safeguards
  before Phase 9 allocation runs, and that the zone endpoints expose no raw provider responses or credentials.

### Manual QA still required

This requires the completed Phase 1, 3, 6, 7, and 8 setup: a migrated PostGIS database, seeded zones, an active
baseline model, complete future zone temperatures, and actual EIA demand at the required one- and 24-hour lags.

1. Run `alembic upgrade head`, then call `POST /api/v1/forecast/run` for a usable future time.
2. Confirm its response has a positive `zone_forecast_count`. Call `GET /api/v1/forecasts/latest`; expect one
   `proxy` record for every active zone, each with a numeric 0-100 risk score and an allowed risk label.
3. Sum latest `predicted_mw` values and compare with the returned city `predicted_demand_mw`. The difference must
   be no more than normal three-decimal rounding.
4. Inspect a hotter and cooler zone. Confirm heat anomaly changes the structured allocation multiplier and the
   hotter zone's proxy share relative to its baseline allocation.
5. Query `GET /api/v1/forecasts/zones/{zone_id}` with a known zone ID and a bounded range. Confirm records are
   chronological, contain the stored model version and explanation, and never claim actual feeder demand.
6. Remove an exact prior-hour zone temperature only in a controlled local dataset. Confirm forecast still labels
   the affected zone medium/low confidence with visible uncertainty. Remove same-time coverage instead; confirm
   `POST /api/v1/forecast/run` rejects the forecast with `forecast_input_not_ready`.
7. Make one source-retrieval time older than `ZONE_FORECAST_MAX_TEMPERATURE_AGE_MINUTES`. Confirm the generated
   record is `data_freshness_status: "stale"` and confidence is `low`; restore the source data afterward.
8. Run the identical forecast again with the same active model. Confirm the zone set is reused and no duplicate
   `zone_forecasts` records or extra `zone_forecasts.generated` audit event is created.

### Known boundary for the next phase

- Resolved in Phase 10: traceable proxy risk forecasts can now create a separately guarded recommendation for
  human review. No recommendation performs an external or grid-control action.

## Phase 10 - Recommendation and safety-guardrail engine details

### How it was implemented

- Added `recommendations`, `recommendation_decisions`, and Alembic migration `20260829_0008`. A recommendation
  references exactly one zone forecast; a database uniqueness rule and one-decision-per-recommendation rule
  prevent duplicate active recommendations and conflicting decisions.
- Added a fixed, code-owned action catalogue. `watch` only monitors/re-checks, `high` verifies reserve capacity
  and prepares voluntary demand response, and `critical` escalates/reviews an approved plan. Every action carries
  an explicit safety boundary stating that no grid, market, customer, or equipment action is executed.
- Updated `POST /api/v1/forecast/run` to evaluate every newly generated or reused zone forecast immediately.
  It exposes recommendation creation/reuse counts and one structured eligibility result per zone.
- Eligibility requires a future proxy forecast, fresh temperature source, confidence at or above the configured
  minimum (`medium` by default), and a risk score at or above the configured minimum (`65`, high risk, by
  default). An ineligible zone creates no recommendation; its explicit reason code is returned and appended as a
  `recommendation.ineligible` audit event.
- Recommendation reasons and evidence are structured JSON derived from persisted risk inputs—not free-form model
  text. Evidence retains proxy MW, temperature/ramp/anomaly, uplift, uncertainty, and the Phase 9 risk formula.
- Recommendations expire at the earlier of their forecast time and the configured 120-minute default. Reads and
  decision attempts safely persist expiry events. A newer zone forecast supersedes any older pending recommendation
  for the same zone, including when the newer forecast becomes ineligible.
- Added `GET /api/v1/recommendations` for pending recommendations by default, with explicit status/history
  options, and `POST /api/v1/recommendations/{id}/decision` for one immutable human `approved`, `rejected`, or
  `deferred` decision. The latter only records a decision; it never executes the recommendation.
- Added audit events for creation, ineligibility, expiry, supersession, and every decision. Decision audit data
  includes only the operator name, decision value, and whether a note exists—not the note text.

### Verification performed

- Python compilation and Ruff checks pass for the full backend, including new recommendation routes, schemas,
  models, services, and migrations.
- FastAPI OpenAPI generation confirms `GET /api/v1/recommendations` and
  `POST /api/v1/recommendations/{recommendation_id}/decision` are registered.
- SQLAlchemy metadata confirms both recommendation tables are registered, and Alembic reports
  `20260829_0008` as the single migration head.

### Manual QA still required

This requires Phase 9's migrated PostGIS database with a fresh, future, high/critical zone forecast and its
active baseline-model prerequisites. Do not paste API keys into chat or commit `backend/.env`.

1. Run `alembic upgrade head`, then use `POST /api/v1/forecast/run` with a qualifying future forecast. Confirm a
   high/critical eligible zone increases `recommendations_created_count` and has `reason_code: "eligible"`.
2. Call `GET /api/v1/recommendations`. Confirm the recommendation has a zone forecast ID, proxy marker, risk,
   structured evidence/reason, bounded action, `pending` status, and an expiry no later than forecast time.
3. Submit `POST /api/v1/recommendations/{id}/decision` with a test operator and `approved`, `rejected`, or
   `deferred`. Confirm a `201` decision record and `GET /api/v1/recommendations?include_inactive=true` reflects
   the final recommendation state.
4. Submit another decision for the same recommendation. Confirm `409 recommendation_not_decidable` and only one
   `recommendation_decisions` database row/audit event.
5. Use stale and low-confidence forecasts. Confirm no pending recommendation is created, the forecast response
   exposes `stale_temperature_data` or `insufficient_confidence`, and an ineligibility audit event is present.
6. Create a new forecast for a zone with an existing pending recommendation. Confirm the older item is
   `superseded`; if the new forecast is eligible it gets one new pending recommendation, otherwise no action
   recommendation remains pending for that zone.
7. Set a short local `RECOMMENDATION_EXPIRY_MINUTES`, wait until expiry, then list or try to decide the item.
   Confirm it becomes `expired`, emits an audit event, and cannot receive a decision.

### Known boundary for the next phase

- Resolved in Phase 11: a manually advanced, durable pipeline can now coordinate heatmap submission, one-shot
  polling, normalization, forecast, risk, and recommendations. It remains development/test controlled and has no
  autonomous scheduler or notification/control integration.

## Phase 11 - Scheduled pipeline and operational safeguards details

### How it was implemented

- Added `pipeline_cycles` and Alembic migration `20260829_0009`. Each durable cycle is uniquely linked to one
  FortyGuard integration job and records trigger source, forecast time, progress/error state, last advance,
  completion, downstream counts, and `fresh`/`stale`/`unavailable` data freshness.
- Added development/test-only `POST /api/v1/cycles/run`, `POST /api/v1/cycles/{id}/advance`, and
  `GET /api/v1/cycles/{id}`. Added `POST /api/v1/demo/run-cycle` as the same locally protected demo trigger;
  Phase 12 will add its replay fixture behavior.
- Every cycle advance performs no more than one FortyGuard poll. If the job is still pending it stores
  `submitted`/`processing` state and returns. When the job completes with successful normalization, the cycle
  invokes the existing city forecast, zone-risk, and guarded recommendation services; no duplicate model/risk or
  recommendation logic was reimplemented.
- Reusing an equivalent heatmap request reuses its request-hashed integration job and its unique cycle. The
  existing unique zone-forecast, recommendation, and decision rules preserve idempotency through downstream
  stages, so overlapping manual requests do not produce duplicate paid jobs or active recommendations.
- Added failure/guardrail paths: terminal provider failures/timeouts mark the cycle `failed`; normalization or
  forecast-data readiness failures mark it `blocked`; each produces a safe audit event and retained error code.
  A `PIPELINE_MAX_POLL_ATTEMPTS` limit marks a still-running job/cycle failed rather than polling indefinitely.
- Added a configurable, conservative 24-hour `FORTYGUARD_DAILY_SUBMISSION_LIMIT` soft budget. It is checked only
  after a duplicate request is recognized and before a new provider submission; a budget block returns a safe
  `429`, records an audit event, and exposes no credentials or provider payload.
- Cycle status includes a data-freshness field. A completed cycle is `fresh` only when every persisted zone
  forecast is fresh; otherwise it is `stale`. Before downstream forecasts exist it remains `unavailable`.

### Verification performed

- Python compilation and Ruff checks pass for the full backend, including the new cycle models, routes,
  orchestration service, budget guard, and migration.
- FastAPI OpenAPI validation confirms the manual cycle, cycle-status, cycle-advance, and demo-run routes are
  registered without replacing existing heatmap/job/forecast routes.
- SQLAlchemy metadata validation confirms `pipeline_cycles` is registered, and Alembic reports
  `20260829_0009` as the migration head.

### Manual QA still required

This requires the completed Phase 1, 3, 6, 8, 9, and 10 database/provider setup, including a valid local
FortyGuard key and a future heatmap request with complete zone coverage. Keep keys only in ignored `backend/.env`.

1. Run `alembic upgrade head`, then call `POST /api/v1/cycles/run` with the valid Phase 4 heatmap body nested as
   `{ "heatmap": { ... } }`. Confirm it returns promptly with a durable cycle and no long-running poll.
2. Use `GET /api/v1/cycles/{id}` between `POST /api/v1/cycles/{id}/advance` calls. Confirm poll attempts, job
   provider status, cycle status, and error code persist through an API restart.
3. Run the exact same cycle request again while the first is active. Confirm `reused: true`, the same job/cycle
   IDs, and no second FortyGuard submission/audit event.
4. After provider completion, confirm the cycle progresses to `completed`, runs forecast/risk/recommendation once,
   and shows accurate zone/recommendation counts and freshness state. Compare with the ordinary forecast and
   recommendation endpoints.
5. Use a provider failure, timeout, incomplete normalized data, or missing model input in controlled local QA.
   Confirm the cycle becomes `failed` or `blocked`, preserves a safe error code, and writes a pipeline audit event.
6. Temporarily lower `PIPELINE_MAX_POLL_ATTEMPTS` and advance a still-processing job. Confirm it stops with
   `pipeline_poll_attempt_limit_exceeded`; restore the setting afterward.
7. Temporarily set a small `FORTYGUARD_DAILY_SUBMISSION_LIMIT`, submit enough distinct small AOIs to reach it, and
   confirm the next new request returns `429 heatmap_submission_budget_exceeded`. Reuse a prior request to confirm
   idempotent reuse still succeeds; restore the local budget afterward.

### Known boundary for the next phase

- Resolved in Phase 12: development/test environments can load a visible, no-network offline replay scenario.
  Phase 13 will add the dedicated audit-history read route, API contract, runbook, CORS review, and complete QA
  pack.

## Phase 12 - Replay mode and demo reliability details

### How it was implemented

- Added the version-controlled 12-hour fixture
  `backend/app/data/replay/houston_watch_to_critical.json`. It is intentionally scrubbed and contains only
  representative scenario values—no credentials, provider headers, signed URLs, customer data, or raw external
  response. The fixture moves Medical Center from `watch` through `high` to `critical` while city demand and heat
  increase.
- Added `app/services/replay_service.py`, which has no EIA or FortyGuard client dependency. With
  `REPLAY_MODE=true`, it uses the existing city/zone models and seeded geometry to create/reuse normal demand
  observations, integration jobs, heatmap runs, zone temperatures, proxy zone forecasts, guarded
  recommendations, completed pipeline cycles, and audit events. This lets the ordinary dashboard-facing read
  routes present the scenario from the database without external calls.
- Added the development/test-only `POST /api/v1/demo/load-replay` endpoint. It returns the scenario, final
  cycle/job IDs, zone-forecast count, recommendation counts, reuse state, and replay disclosure. It returns a
  safe `409 replay_mode_disabled` response until `REPLAY_MODE=true` is configured.
- Updated `POST /api/v1/demo/run-cycle`: when replay is enabled it needs no request body and executes the same
  no-network replay loader; otherwise it keeps the prior protected live heatmap-request behavior.
- Added the shared `DataModeResponse` envelope and made health, zones, demand, temperatures, city/zone forecasts,
  recommendations, heatmaps, jobs, and cycles return `data_mode: "live" | "replay"`. Existing endpoint data
  shapes remain nested under their `data` field.
- Replay uses standard persisted schemas and the existing recommendation service where practical. Fixture-backed
  zone forecasts remain deterministic so the system does not pretend to retrain a model or call a live provider.
  The loader writes `replay.loaded` and `replay.cycle_run` audit events; Phase 13 will provide the dedicated
  audit-history read API.

### Verification performed

- Python compilation and Ruff checks pass across the backend application and migrations after adding replay
  routes, schemas, fixture loader, and API envelopes.
- Fixture-contract verification confirms exactly twelve hourly records and a Medical Center risk transition from
  `50` (`watch`) to `91` (`critical`).
- FastAPI OpenAPI generation confirms both `/api/v1/demo/load-replay` and `/api/v1/demo/run-cycle` are registered,
  and response-schema inspection confirms the public `data_mode` field is exposed.
- No schema migration was required: replay writes through existing Phase 1-11 tables and preserves
  `20260829_0009` as the migration head.

### Manual QA still required

This requires a migrated local PostGIS database. Do not add keys to demonstrate replay; leave both external keys
blank in ignored `backend/.env`.

1. Set `APP_ENV=development` and `REPLAY_MODE=true`, leave `EIA_API_KEY` and `FORTYGUARD_API_KEY` empty, then run
   `alembic upgrade head` and start the API.
2. Call `POST /api/v1/demo/load-replay` with no body. Expect `201`, `data_mode: "replay"`, a scenario name, a
   completed cycle/job, 96 zone forecasts (8 zones × 12 hours), and no external API requirement.
3. Call `GET /api/v1/health`, `/api/v1/zones`, `/api/v1/data/demand`, `/api/v1/forecasts/latest`,
   `/api/v1/recommendations`, and `/api/v1/cycles/{cycle_id}`. Confirm every response has
   `data_mode: "replay"` and the returned objects are coherent with the loader result.
4. Fetch the Medical Center timeline with `GET /api/v1/forecasts/zones/{zone_id}`. Confirm early entries are
   `watch`, later entries are `high`, and the final entry is `critical`. Confirm the final high/critical forecast
   can produce the bounded, human-review recommendation and no operational action occurs.
5. Call `POST /api/v1/demo/run-cycle` with no body. Confirm it completes/reuses the offline replay path and does
   not need valid EIA/FortyGuard keys. Repeat `POST /api/v1/demo/load-replay` to confirm duplicate-safe reuse.
6. Set `REPLAY_MODE=false` and restart. Confirm `/api/v1/demo/load-replay` returns `409 replay_mode_disabled`,
   while `/api/v1/demo/run-cycle` again requires the normal safe live heatmap request body. Restore your desired
   local setting afterward.

### Known boundary for the next phase

- The repository does not contain a completed real-provider capture, so the committed numbers are clearly labeled
  deterministic representative replay data. An approved scrubbed FortyGuard/EIA capture can replace those values
  later without changing the replay contract.
- Resolved in Phase 13: audit history is readable through a redacted, paginated API and the final contract,
  startup/deployment guide, CORS policy, and end-to-end QA pack are documented. Environment-backed QA remains
  listed below.

## Phase 13 - API hardening, documentation, and manual QA pack details

### How it was implemented

- Added `GET /api/v1/audit-events`, a read-only audit-history route with bounded 1–500 item pagination, optional
  event/entity/time filters, newest-first ordering, and total/count metadata. Its payload reader redacts
  credential-like keys and truncates deep, long, or oversized values, so the QA UI cannot use the audit trail to
  retrieve API keys, signed URLs, or raw provider responses.
- Added bounded `limit`, `offset`, `count`, and `total` response fields to the demand, normalized-temperature,
  zone-forecast timeline, and recommendation list routes. Fixed-size map/forecast-set routes remain explicitly
  unpaginated because the complete configured set is the API contract.
- Added predictable safe infrastructure and input errors. Missing database configuration now returns
  `503 database_not_configured`; database failures return `503 database_unavailable`; malformed requests return a
  safe `422 invalid_request` envelope without echoing submitted values.
- Added a restrictive comma-separated `CORS_ALLOWED_ORIGINS` setting. The default permits only local frontend
  origins on ports 3000, allows only `GET`/`POST` with `Content-Type`, does not allow credentials, and does not use
  wildcard origins.
- Added OpenAPI tag descriptions for every route group, including the explicit decision-support and replay safety
  boundaries, making `/docs` easier for frontend developers and QA to navigate.
- Added `backend/docs/api-contract.md` with public route inventory, representative request/response/error payloads,
  pagination, CORS, and safety rules. Added `backend/docs/manual-qa.md` with clean setup, full live/replay flows,
  expected outcomes, negative checks, and defect-recording format.
- Extended `backend/README.md` with local startup, deployment checklist, troubleshooting, CORS configuration, and
  reproducible lint/type/compile/startup validation commands. Added Mypy to the development dependencies and a
  focused Phase 13 static type-check configuration covering the new/changed API boundary modules and schemas.

### Verification performed

- Python compilation and Ruff checks pass across the complete backend and migrations.
- Mypy passes for the 23 Phase 13 API/config/schema/audit boundary source files configured in `pyproject.toml`.
- FastAPI OpenAPI generation confirms the audit route, readable tags, safe response schemas, `data_mode`, and list
  pagination fields are registered.
- The production-style Uvicorn command successfully starts the application at `127.0.0.1:8013`.
- Alembic reports `20260829_0009` as the sole migration head. No new database migration is required because Phase
  13 reads existing audit records and adds no persisted fields.

### Manual QA still required

The full phase QA pack is now in `backend/docs/manual-qa.md`. Docker is not installed on this workstation, so a
clean PostGIS migration, seeded-database run, and real-provider workflow could not be executed here.

1. On a fresh profile with Docker/PostGIS, follow the clean setup and every live/replay/negative workflow in the
   manual QA runbook exactly.
2. Confirm `GET /api/v1/audit-events` paginates and redacts payloads while showing the expected lifecycle events.
3. Confirm every paginated dashboard timeline exposes coherent `count`, `total`, `limit`, and `offset` values.
4. Confirm the production frontend’s exact HTTPS origin is the only allowed CORS origin before deployment.
5. Record defects using the runbook’s endpoint/request/expected/actual/evidence format.

### Final backend status

- The backend MVP is ready for frontend integration and manual QA: its public contract, replay disclosure,
  development controls, safety boundaries, error shapes, audit reads, and operating guidance are documented.
- Remaining verification is environmental rather than a missing backend implementation: clean PostGIS migration
  execution, live EIA/FortyGuard credentials, and a final frontend-origin browser test.

## Secrets reminder

- Do not commit `.env` files.
- Do not paste either API key in chat or source code.
- The local backend file must use these exact names:
  - `EIA_API_KEY=...`
  - `FORTYGUARD_API_KEY=...`
