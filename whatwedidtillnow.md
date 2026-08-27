# What We Did Till Now

This file tracks completed work and how it was implemented. Update it at the end of every implementation phase.

## Project decisions

- **Project:** Energy Grid Heat-Demand Forecaster.
- **Demo location:** Houston, Texas, using ERCOT data for real historical grid-demand calibration.
- **Core data:** FortyGuard heatmaps for temperature and EIA/ERCOT sources for historical demand.
- **Safety boundary:** recommendations only; never direct control of electric-grid equipment.
- **Backend stack:** Python 3.12, FastAPI, PostgreSQL/PostGIS, SQLAlchemy, Alembic, Redis/Celery later.

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
| 5 - Async polling | Not started | Celery/Redis workers and status polling |
| 6-13 | Not started | Data aggregation, model, risk, recommendations, scheduler, replay mode, and QA pack |

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
  and does not expose a job-status endpoint yet. Phase 5 will add Celery/Redis polling, transient-404
  handling, terminal status updates, and controlled result capture.

## Secrets reminder

- Do not commit `.env` files.
- Do not paste either API key in chat or source code.
- The local backend file must use these exact names:
  - `EIA_API_KEY=...`
  - `FORTYGUARD_API_KEY=...`
