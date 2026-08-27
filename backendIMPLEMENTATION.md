# Energy Grid Backend Implementation Plan

## Purpose

This document is the step-by-step implementation plan for the **backend only** of Energy Grid Heat-Demand Forecaster. It is designed to be handed to an AI agent one phase at a time. Each phase is intentionally small, has a clear boundary, and ends with a manual QA checklist.

The backend will:

- collect heatmap data from FortyGuard;
- collect real historical grid-demand data from EIA;
- store and process zone-level temperature and demand data;
- create a transparent demand forecast and risk score;
- generate safe recommendations for a human operator;
- expose an API that the future frontend dashboard can consume;
- maintain a full audit trail.

It will **not** control a real electricity grid, send customer messages, or connect to SCADA/utility-control systems.

## Fixed product scope

### In scope for the hackathon MVP

- One US demo city/grid area.
- 6-12 manually defined operational zones.
- Real EIA hourly demand data for historical model calibration.
- FortyGuard heatmap temperatures and up-to-12-hour forecast inputs.
- Zone-level demand **estimates** and risk scores, not measured feeder demand.
- Human approval/rejection/defer workflow for recommendations.
- Manual QA by the project owner.
- Cached/replay mode using completed real-source API results.

### Out of scope

- Autonomous control of grid assets.
- Feeder-level claims without an actual utility feeder dataset.
- User accounts, roles, billing, multi-tenancy, payments, or mobile app.
- A production-grade MLOps platform.
- Satellite, Street View, and Heat Intelligence endpoints in the first MVP. They are optional future enrichments.

## Architecture decisions

Use a single Python service with background workers. Keep the system simple enough to finish, but structured enough to be credible.

```text
Future web dashboard
       |
       v
FastAPI REST API ----------------------> PostgreSQL + PostGIS
       |                                        |
       |                                        +--> zones, jobs, temperatures, demand,
       |                                             forecasts, recommendations, audit log
       v
Redis queue <---- Celery worker/scheduler
       |                 |              |
       |                 v              v
       |          FortyGuard API      EIA API / downloaded EIA CSV
       |
       +--> job state and retry coordination
```

### Technology choices

| Need | Choice | Reason |
| --- | --- | --- |
| API | Python 3.12 + FastAPI | Clean typed API, excellent data and async ecosystem |
| Validation/config | Pydantic v2 + pydantic-settings | Reliable request validation and `.env` configuration |
| Database | PostgreSQL 16 + PostGIS | Stores time series, GeoJSON zones, and audit records |
| ORM/migrations | SQLAlchemy 2 + Alembic | Explicit models and repeatable database migrations |
| Background jobs | Celery + Redis | Handles FortyGuard submit/poll tasks outside HTTP requests |
| HTTP client | httpx | Timeouts, mocking capability, and async-compatible client |
| Data/model | pandas + NumPy + scikit-learn | Transparent demand model without unnecessary complexity |
| Geospatial | Shapely + GeoPandas | Validates zones and aggregates heatmap tile data into zones |
| Logging | Python logging, JSON-style structured events | Easy troubleshooting without exposing secrets |
| Local setup | Docker Compose | One-command database/Redis setup across machines |

Do not add an LLM to calculate demand or risk. Deterministic model and rules create the source-of-truth result. If an LLM is added later, it may rewrite the already-approved structured explanation into plain language only.

## Before coding: decisions the owner must make

These are one-time product decisions. Do not start data integration until the first four are decided.

| Decision | Required choice | Recommended initial choice |
| --- | --- | --- |
| Demo area | One US city/grid area | Pick an area that has EIA subregion demand available |
| Demand source | EIA balancing-authority or EIA subregion series | EIA Form 930 subregion if available; otherwise balancing authority |
| Zones | 6-12 polygons and names | Manually authored GeoJSON zones within the selected city |
| Temperature baseline | Cooling threshold | 18°C, configurable per demo city |
| Granularity | FortyGuard heatmap tile size | Start at 80 m; use 100 m if job volume is too large |
| Time zone | Canonical storage time zone | Store all timestamps in UTC; return UTC plus local zone metadata |
| Risk thresholds | Low/watch/high/critical bands | 0-39, 40-64, 65-79, 80-100 |
| Human approval identity | Initial operator identity | Simple `operator_name` text field; no authentication in MVP |

## Required accounts, secrets, and software

### Accounts and secrets

- FortyGuard API key. Keep only in local `.env` / deployment secrets.
- Free EIA API key. It is needed for automated EIA downloads.
- Optional: a Postgres host and Redis host for deployment.
- Optional: Sentry DSN for error reporting.

### Local software

- Git
- Docker Desktop (or local PostgreSQL + PostGIS and Redis)
- Python 3.12
- A package manager: `uv` is preferred; `pip` is acceptable
- An API client for manual QA: Postman, Bruno, Insomnia, or curl

### Never commit

- `.env`
- FortyGuard or EIA API keys
- temporary FortyGuard signed report links
- production database exports containing operator decisions

## Repository structure

Create the backend under `backend/`. Keep the current Markdown documents at the repository root.

```text
EnergyGridForutyGaurd/
├── EnergyGrid.md
├── apifourtygaurd.md
├── backendIMPLEMENTATION.md
├── backend/
│   ├── pyproject.toml
│   ├── uv.lock
│   ├── .env.example
│   ├── .gitignore
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── alembic.ini
│   ├── alembic/
│   │   └── versions/
│   ├── app/
│   │   ├── main.py
│   │   ├── api/
│   │   │   ├── router.py
│   │   │   └── v1/
│   │   │       ├── health.py
│   │   │       ├── zones.py
│   │   │       ├── jobs.py
│   │   │       ├── forecasts.py
│   │   │       ├── recommendations.py
│   │   │       └── demo.py
│   │   ├── core/
│   │   │   ├── config.py
│   │   │   ├── database.py
│   │   │   ├── logging.py
│   │   │   └── exceptions.py
│   │   ├── db/
│   │   │   ├── base.py
│   │   │   ├── models/
│   │   │   └── repositories/
│   │   ├── schemas/
│   │   ├── services/
│   │   │   ├── fortyguard_client.py
│   │   │   ├── eia_client.py
│   │   │   ├── heatmap_service.py
│   │   │   ├── zone_aggregation_service.py
│   │   │   ├── demand_data_service.py
│   │   │   ├── forecasting_service.py
│   │   │   ├── risk_service.py
│   │   │   ├── recommendation_service.py
│   │   │   └── replay_service.py
│   │   ├── workers/
│   │   │   ├── celery_app.py
│   │   │   ├── tasks.py
│   │   │   └── scheduler.py
│   │   ├── data/
│   │   │   ├── seed/
│   │   │   └── replay/              # small, scrubbed real-source fixtures only
│   │   └── scripts/
│   │       ├── seed_zones.py
│   │       ├── import_eia_data.py
│   │       ├── train_model.py
│   │       └── run_demo_cycle.py
│   ├── docs/
│   │   ├── api-contract.md
│   │   └── manual-qa.md
│   └── tests/                       # add only if automated tests are approved later
└── frontend/                         # created later; not part of this backend plan
```

## Environment configuration

Create `backend/.env.example`. It must contain placeholders only:

```dotenv
APP_ENV=development
APP_NAME=energy-grid-api
API_V1_PREFIX=/api/v1
LOG_LEVEL=INFO

DATABASE_URL=postgresql+psycopg://energygrid:energygrid@localhost:5432/energygrid
REDIS_URL=redis://localhost:6379/0

FORTYGUARD_BASE_URL=https://api.fortyguard.com
FORTYGUARD_API_KEY=
FORTYGUARD_DEFAULT_GRANULARITY=80
FORTYGUARD_POLL_SECONDS=5
FORTYGUARD_MAX_POLL_SECONDS=600

EIA_BASE_URL=https://api.eia.gov/v2
EIA_API_KEY=

DEMO_CITY_NAME=
DEMO_TIMEZONE=
COOLING_BASE_TEMPERATURE_C=18
REPLAY_MODE=false
```

The API must refuse live FortyGuard/EIA operations if a required key is absent. It must still start in `REPLAY_MODE=true` when replay fixtures exist.

## Data model

Use migrations for every table change. IDs are UUIDs. Store timestamps as timezone-aware UTC values.

| Table | Purpose | Essential fields |
| --- | --- | --- |
| `cities` | Demo area configuration | `id`, `name`, `timezone`, `country_code`, `geometry` |
| `zones` | Operational polygons | `id`, `city_id`, `name`, `code`, `geometry`, `active`, `allocation_weight` |
| `integration_jobs` | Every FortyGuard request/poll lifecycle | `id`, `provider`, `operation`, `status`, `external_activity_id`, `request_hash`, `requested_at`, `completed_at`, `error_code` |
| `heatmap_runs` | Context of a completed/requested heatmap | `id`, `job_id`, `requested_time`, `granularity_m`, `analytic_type`, `aoi_geometry`, `source_kind` |
| `zone_temperature_observations` | Aggregated heatmap result per zone/hour | `id`, `zone_id`, `observed_for`, `mean_c`, `min_c`, `max_c`, `stddev_c`, `tile_count`, `source_run_id`, `is_forecast` |
| `demand_observations` | Real EIA historical series | `id`, `city_id`, `period_utc`, `source`, `source_area_code`, `demand_mw`, `is_actual`, `quality_flag` |
| `model_versions` | Reproducible model metadata | `id`, `name`, `version`, `trained_at`, `metrics_json`, `artifact_path`, `feature_schema_json` |
| `zone_forecasts` | Forecasted load/risk per zone/hour | `id`, `zone_id`, `forecast_for`, `model_version_id`, `temperature_c`, `cdh`, `baseline_mw`, `predicted_mw`, `uplift_pct`, `risk_score`, `risk_level`, `confidence` |
| `recommendations` | Decision-support output | `id`, `zone_forecast_id`, `action_code`, `reason`, `status`, `created_at`, `expires_at` |
| `recommendation_decisions` | Human action on recommendation | `id`, `recommendation_id`, `decision`, `operator_name`, `note`, `decided_at` |
| `audit_events` | Append-only trace record | `id`, `event_type`, `entity_type`, `entity_id`, `payload_json`, `created_at` |

Data rules:

- `zone_forecasts` must retain the model version used.
- `recommendation_decisions.decision` is only `approved`, `rejected`, or `deferred`.
- One forecast time may have multiple zones; do not overwrite historical forecasts.
- A risk score is always numeric 0-100, even if the UI also shows a label.
- Any estimated zone allocation must retain `allocation_weight` and a clear `estimated`/`proxy` marker.

## Backend API contract for the future frontend

All routes start with `/api/v1`. JSON only. ISO-8601 timestamps in UTC.

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/health` | API, database, Redis, and replay-mode health |
| `GET` | `/cities/current` | Selected demo city and configuration |
| `GET` | `/zones` | Active zones including GeoJSON geometry |
| `POST` | `/zones` | Create a zone in development/admin mode |
| `POST` | `/data/eia/import` | Trigger/import a defined historical EIA range |
| `GET` | `/data/demand` | Return demand observations by time range |
| `POST` | `/heatmaps/submit` | Submit a FortyGuard heatmap job for a time/AOI |
| `GET` | `/jobs/{job_id}` | Return our stored job status, never provider secrets |
| `POST` | `/jobs/{job_id}/poll` | Development-only manual poll trigger |
| `POST` | `/forecast/run` | Generate forecasts from available normalized inputs |
| `GET` | `/forecasts/latest` | Latest forecast set for all zones |
| `GET` | `/forecasts/zones/{zone_id}` | Zone timeline and explanations |
| `GET` | `/recommendations` | Pending/recent recommendations |
| `POST` | `/recommendations/{id}/decision` | Approve, reject, or defer; records audit event |
| `GET` | `/audit-events` | Paginated audit history |
| `POST` | `/demo/load-replay` | Load approved cached scenario; development/demo only |
| `POST` | `/demo/run-cycle` | Run a complete replay pipeline; development/demo only |

Success responses should include `data`; errors should include `error.code`, `error.message`, and optional safe `error.details`. Never return keys, signed URLs, raw provider request headers, or unbounded raw heatmap payloads to the frontend.

## Manual QA policy

The project owner performs official functional testing manually. AI agents should:

- run formatting, static/type checks, migration checks, and startup checks;
- provide exact manual QA instructions and expected JSON/UI-visible outcomes after each phase;
- not mark a phase complete until its manual QA checklist is documented;
- not create a large automated test suite unless specifically requested later.

Manual QA should be performed in Postman/Bruno first. Save one collection/environment file that contains only local URLs and variable names, never real secrets.

## Phase-by-phase delivery plan

### Phase 0 - Project foundation and developer setup

**Goal:** create a clean, runnable backend skeleton with no business logic.

**Build tasks**

1. Create the `backend/` structure above.
2. Initialize Python project and install runtime/dev dependencies.
3. Add FastAPI app with versioned router and `GET /api/v1/health`.
4. Add Pydantic settings and `.env.example`.
5. Add Docker Compose services for PostgreSQL/PostGIS and Redis.
6. Add formatter/linter/type-check commands to README or Makefile.
7. Add `.gitignore` that excludes `.env`, caches, virtual environments, and local database volumes.

**Definition of done**

- API starts locally.
- `GET /api/v1/health` returns app status and says database/Redis are not yet checked or are healthy.
- No secrets appear in tracked files.

**Manual QA**

1. Copy `.env.example` to `.env` and leave API keys blank.
2. Start local services and API.
3. Open `/docs` and call `GET /api/v1/health`.
4. Confirm health response does not expose environment variables or credentials.

**Handoff to next phase:** working app, compose setup, and startup instructions.

### Phase 1 - Database foundation and migrations

**Goal:** connect to Postgres/PostGIS and create the core schema.

**Build tasks**

1. Configure SQLAlchemy engine/session and Alembic.
2. Enable PostGIS through the initial migration.
3. Create migrations/models for `cities`, `zones`, `integration_jobs`, and `audit_events`.
4. Add database health check.
5. Add a seed script that creates one selected demo city but no zones yet.

**Definition of done**

- Fresh database can be migrated from zero.
- API health reports database connectivity.
- One city can be seeded repeatedly without duplicate records.

**Manual QA**

1. Start with an empty local database volume.
2. Run migrations and city seed script.
3. Check database with a GUI or SQL query: tables exist and city exists once.
4. Restart API and confirm database health remains `healthy`.

**Handoff to next phase:** migration history and city configuration.

### Phase 2 - Zone management and GeoJSON validation

**Goal:** store 6-12 valid operational zones safely.

**Build tasks**

1. Implement zone schemas and repository/service.
2. Add `GET /zones` and development-only `POST /zones`.
3. Validate GeoJSON Feature/Polygon input, closed rings, valid geometry, and selected-city containment.
4. Add `seed_zones.py` that imports a version-controlled `zones.geojson` file.
5. Store a simple `allocation_weight` per zone; ensure all active zone weights sum to 1.0.
6. Add audit event for create/update/import operations.

**Definition of done**

- Valid zones can be imported and returned as GeoJSON.
- Invalid geometry is rejected with a clear `400` response.
- Zone codes and names are unique per city.

**Manual QA**

1. Import 6-12 zone polygons.
2. Call `GET /zones`; confirm names, codes, and geometry are correct.
3. Submit an unclosed/invalid polygon; confirm it is rejected, not saved.
4. Confirm weights sum to 1.0 and no zones overlap unintentionally.

**Handoff to next phase:** final `zones.geojson` for the chosen demo area.

### Phase 3 - EIA demand-data ingestion

**Goal:** download and store real hourly EIA demand observations.

**Build tasks**

1. Implement `eia_client.py` with API-key handling, explicit timeout, pagination, date-range validation, and safe errors.
2. Make EIA route/area code configuration-driven; do not hard-code a city or provider key in Python.
3. Implement demand normalization: source timestamp, UTC conversion, actual/forecast flag, demand MW, source area, quality flag.
4. Create migration/model for `demand_observations`.
5. Implement `import_eia_data.py` and `POST /data/eia/import` for a bounded historical date range.
6. Add `GET /data/demand` with validated start/end filters.
7. Reject duplicate observations with a unique source/area/timestamp key.

**Definition of done**

- At least one real historical hot-weather period is stored as hourly MW observations.
- Re-running the same import does not duplicate data.
- Missing EIA API key produces a clear configuration error.

**Manual QA**

1. Register an EIA key and add it locally to `.env`.
2. Import a 7-day period around a known hot day.
3. Query the stored data and compare several returned values/timestamps with the EIA portal.
4. Run the same import again; confirm record count does not grow unexpectedly.
5. Request an invalid date range; confirm a readable validation response.

**Handoff to next phase:** verified area code, history date range, and imported demand dataset.

### Phase 4 - FortyGuard client and job persistence

**Goal:** submit a valid heatmap task without blocking the API request.

**Build tasks**

1. Implement `fortyguard_client.py`; keep request building isolated from application services.
2. Validate heatmap request inputs: US AOI, area limit, date/time, granularity (60/80/100), and `tcm` analytic type.
3. Create migrations/models for `integration_jobs` and `heatmap_runs`.
4. Implement `POST /heatmaps/submit`.
5. Calculate a canonical request hash; return an existing active/completed job when the same request already exists.
6. Persist our job ID and FortyGuard `activity_id`; never return provider secrets.
7. Record audit events for request submission and validation failures.

**Definition of done**

- A valid request produces an internal job record and external activity ID.
- Duplicate request does not create extra paid FortyGuard submissions.
- Missing/invalid FortyGuard key gives a safe failure message.

**Manual QA**

1. Add a FortyGuard key locally.
2. Submit a small 80/100 m AOI with a valid current/historical time.
3. Confirm API returns internal `job_id` and `submitted` status.
4. Submit the same body again; confirm the returned job is reused.
5. Submit invalid geometry/granularity; confirm it is blocked before provider submission.

**Handoff to next phase:** one or more persisted FortyGuard jobs, including their safe request metadata.

### Phase 5 - Asynchronous polling and raw-result capture

**Goal:** reliably move a submitted heatmap job to completed or failed state.

**Build tasks**

1. Configure Celery/Redis and worker startup commands.
2. Create submit-follow-up/poll task(s) with bounded retry and backoff.
3. Treat initial `404` from FortyGuard as transient; stop on case-insensitive completed/succeeded/failed/error statuses.
4. Enforce maximum polling window from configuration.
5. Persist provider status, completion time, safe error metadata, and raw response in controlled storage/JSON field.
6. Add `GET /jobs/{job_id}` and development-only `POST /jobs/{job_id}/poll`.
7. Do not log raw signed URLs, keys, or excessively large payloads.

**Definition of done**

- Worker processes a real submitted task without holding an HTTP request open.
- Job reaches `completed`, `failed`, or `timed_out` with a useful reason.
- Restarting API/worker does not create duplicate provider submissions.

**Manual QA**

1. Start API, Postgres, Redis, and worker.
2. Submit a heatmap then poll `GET /jobs/{job_id}` until terminal state.
3. Verify the job has the expected provider activity ID and completion time.
4. Stop/restart worker while processing; confirm job state remains recoverable.
5. Use an intentionally invalid request and confirm it ends cleanly without retries forever.

**Handoff to next phase:** a completed heatmap payload stored against a heatmap run.

### Phase 6 - Heatmap normalization and zone aggregation

**Goal:** convert FortyGuard tile GeoJSON into zone temperature observations.

**Build tasks**

1. Create migration/model for `zone_temperature_observations`.
2. Parse and validate completed `map_data` GeoJSON.
3. Spatially join/intersect tiles with zones; define and document whether assignment uses tile centroid or area-weighted intersection. Use one approach consistently.
4. Calculate per-zone mean/min/max/standard deviation/tile count.
5. Mark observation `is_forecast` based on requested source time relative to execution time.
6. Persist source run ID and data freshness.
7. Add query endpoint(s) for zone temperature timeline.

**Definition of done**

- One completed heatmap creates one temperature record per overlapping active zone.
- Zones without tiles are explicitly marked missing; they do not silently get a zero temperature.
- Aggregated values can be traced to the source heatmap run.

**Manual QA**

1. Use a completed heatmap covering all zones.
2. Query the zone temperatures and compare mean/min/max with visually plausible map areas.
3. Submit a heatmap outside the zones; confirm zero observations or a clear no-overlap result.
4. Confirm tile count and source run IDs are present.

**Handoff to next phase:** normalized historical/current/forecast zone temperature observations.

### Phase 7 - Data preparation and Cooling Degree Hours features

**Goal:** prepare repeatable model features from real demand and temperatures.

**Build tasks**

1. Implement time alignment between EIA demand and FortyGuard temperature in UTC/local demo timezone.
2. Compute Cooling Degree Hours: `max(0, temperature_c - baseline_c)`.
3. Create calendar features: local hour, day of week, weekend, month, and optional holiday flag.
4. Define treatment of missing observations: record missing data; never silently interpolate without metadata.
5. Build a versioned feature dataset script and data-quality report.
6. Add a model-ready schema/contract in `docs/`.

**Definition of done**

- A reproducible dataset can be built for a defined historical period.
- Every row has a source timestamp, target demand MW, and feature quality status.
- CDH calculation is configurable by city baseline.

**Manual QA**

1. Choose five known temperatures and manually calculate CDH; compare with backend output.
2. Inspect several time-aligned demand/temperature rows around a timezone/DST change if applicable.
3. Confirm missing data is reported clearly in the quality report.

**Handoff to next phase:** clean feature dataset and documented feature list.

### Phase 8 - Baseline demand forecast model

**Goal:** train a transparent city/grid-level demand forecast model.

**Build tasks**

1. Start with a baseline regression model using calendar features, lagged demand, and CDH.
2. Use a chronological train/validation split. Never shuffle time-series data.
3. Calculate MAE, RMSE, and MAPE; store them in `model_versions`.
4. Persist model artifact locally/deployment storage with model/version metadata.
5. Implement a forecasting service that loads one explicit active model version.
6. Add `scripts/train_model.py` and a controlled `POST /forecast/run` execution path.
7. Make failure explicit when no trained model exists.

**Definition of done**

- Model forecasts an hourly city/grid demand value for the next available forecast time.
- Model metrics are stored and available to the API.
- The app labels the forecast as an estimate, not a measurement.

**Manual QA**

1. Train using a documented date range.
2. Review returned MAE/RMSE/MAPE and compare predicted vs actual on a validation chart/export.
3. Trigger an example forecast and ensure it uses the named model version.
4. Temporarily remove model artifact/config; confirm the API fails safely with an understandable message.

**Handoff to next phase:** approved baseline model version and a recorded validation result.

### Phase 9 - Zone demand allocation and risk scoring

**Goal:** turn city-level forecast into explainable per-zone risk.

**Build tasks**

1. Use zone allocation weights plus heat anomaly to distribute predicted load across zones.
2. Calculate heat anomaly, temperature ramp rate, demand uplift percent, and uncertainty penalty.
3. Implement deterministic risk formula and labels:
   - 0-39 low
   - 40-64 watch
   - 65-79 high
   - 80-100 critical
4. Create `zone_forecasts` and `model_versions` migrations/models if not already present.
5. Persist all contributing values and a short structured explanation.
6. Add `GET /forecasts/latest` and `GET /forecasts/zones/{zone_id}`.
7. Include `estimate_type: "proxy"` in responses until real zone/feeder demand exists.

**Definition of done**

- Every active zone with valid input receives a 0-100 risk score and label.
- The sum of allocated zone forecast demand is approximately the city forecast, subject to rounding.
- Missing or stale input lowers confidence and is visible in output.

**Manual QA**

1. Run forecasting with a known hot period; inspect all zone records.
2. Confirm all risk scores are inside 0-100 and labels match threshold bands.
3. Add the zone predicted MW values; confirm they approximately equal the city-level forecast.
4. Make one input stale/missing; confirm forecast exposes reduced confidence or skips recommendation eligibility.

**Handoff to next phase:** a complete 12-hour zone forecast set with traceable calculations.

### Phase 10 - Recommendation and safety-guardrail engine

**Goal:** generate bounded recommendations, never autonomous actions.

**Build tasks**

1. Define action catalogue in code/config:
   - watch -> monitor/recheck;
   - high -> verify reserve capacity / prepare voluntary demand response;
   - critical -> escalate to duty operator and review approved response plan.
2. Implement recommendation eligibility rules: valid forecast, sufficient confidence, fresh temperature data, risk threshold, no duplicate active recommendation.
3. Create migrations/models for `recommendations` and `recommendation_decisions`.
4. Generate machine-readable reason/evidence from structured data, not free-form model text.
5. Add `GET /recommendations` and `POST /recommendations/{id}/decision`.
6. Append audit events for creation, expiry, and every human decision.
7. Add expiration/replacement behavior when a newer forecast supersedes a recommendation.

**Definition of done**

- High/critical eligible zone creates one understandable recommendation.
- Low-confidence or stale data produces no action recommendation and explains why.
- Decisions are immutable records and no endpoint performs grid control.

**Manual QA**

1. Use a high-risk forecast; confirm recommendation has zone, risk, reason, action, and expiry.
2. Approve it with a test operator name and note; confirm audit record exists.
3. Try to decide it again; confirm business rule prevents conflicting duplicate decision.
4. Use stale data; confirm no actionable recommendation is created.

**Handoff to next phase:** end-to-end human-supervised decision workflow.

### Phase 11 - Scheduled pipeline and operational safeguards

**Goal:** run the full cycle safely on a schedule.

**Build tasks**

1. Add a configurable scheduler cadence; start with every 60 minutes, not every few minutes.
2. Implement cycle orchestration: submit -> poll -> normalize -> forecast -> risk -> recommend -> audit.
3. Add idempotency guards so an overlapping cycle cannot create duplicate provider jobs/forecasts/recommendations.
4. Add data-freshness rules and a stale-data status endpoint/field.
5. Add provider-failure handling, retry limits, job timeout alerts/logs, and soft credit budget checks.
6. Add `POST /demo/run-cycle` for manually triggering the same orchestration in development.

**Definition of done**

- A scheduled/manual cycle creates one clean set of outputs without duplicate work.
- Any failed stage leaves an understandable audit/job trail.
- API remains responsive while workers operate.

**Manual QA**

1. Run a manual complete cycle and follow job status to forecast/recommendation.
2. Trigger the cycle twice quickly; confirm only one active request exists for the same inputs.
3. Simulate provider failure by using an invalid local key/endpoint; confirm the error is safe and visible.
4. Confirm scheduler does not run a new cycle before the existing same-slot cycle completes.

**Handoff to next phase:** reliable daily/periodic orchestration.

### Phase 12 - Replay mode and demo reliability

**Goal:** preserve a live-data-quality demonstration when external APIs are slow or unavailable.

**Build tasks**

1. Create a small scrubbed fixture set from completed real FortyGuard/EIA results. Never include keys or signed URLs.
2. Add `REPLAY_MODE` config and a clear API field: `data_mode: "live" | "replay"`.
3. Implement `POST /demo/load-replay` and `POST /demo/run-cycle` with safe development/demo environment restriction.
4. Populate a compelling scenario: one or more zones transition from watch to high/critical within 12 hours.
5. Ensure replay output uses the same application services/schemas as live data where practical.

**Definition of done**

- System can present city, zones, forecast, risk, recommendation, and audit history with no external network calls.
- The UI/API can visibly disclose replay mode.

**Manual QA**

1. Disable/omit external API keys.
2. Start with `REPLAY_MODE=true` and load the scenario.
3. Verify all dashboard-facing API routes return coherent data.
4. Confirm responses clearly state `data_mode: replay`.

**Handoff to next phase:** stable offline demo scenario.

### Phase 13 - API hardening, documentation, and manual QA pack

**Goal:** make the backend easy to hand to frontend development and manual QA.

**Build tasks**

1. Review all routes for validated inputs, stable response schemas, pagination, and safe errors.
2. Add CORS configuration for the chosen frontend origin; use restrictive development defaults.
3. Add API tags/descriptions so FastAPI `/docs` is readable.
4. Write `backend/docs/api-contract.md` with representative request/response payloads.
5. Write `backend/docs/manual-qa.md` using all phase QA checks as one end-to-end test script.
6. Add startup/deployment/runbook instructions and a troubleshooting section.
7. Run formatting, linting, type checking, migration-on-empty-DB check, and production-style startup check.

**Definition of done**

- A new developer can run the backend locally from the documentation.
- QA can execute the complete workflow without reading source code.
- Frontend team has stable routes and example payloads.

**Manual QA**

1. Use a fresh machine/profile or follow setup instructions from zero.
2. Run all documented API calls in order: health -> zones -> demand -> job -> temperatures -> forecast -> recommendation -> decision -> audit.
3. Repeat using replay mode.
4. Record defects with endpoint, request body without secrets, expected result, actual result, and screenshot/response.

**Handoff:** backend MVP ready for frontend integration and manual QA.

## Phase order and implementation rule

```text
0 Foundation
  -> 1 Database
  -> 2 Zones
  -> 3 EIA demand data
  -> 4 FortyGuard submit
  -> 5 Worker polling
  -> 6 Heatmap aggregation
  -> 7 Feature dataset
  -> 8 City demand model
  -> 9 Zone risk forecast
  -> 10 Recommendations/approval
  -> 11 Scheduler/guardrails
  -> 12 Replay mode
  -> 13 Hardening and QA pack
```

An AI agent receives **one phase only**. It must not start later phases, refactor unrelated completed work, invent user-facing features, or change the agreed tech stack without recording the reason and getting approval.

## Standard agent handoff prompt

Use this prompt when assigning a phase:

```text
Implement only Phase <number> from backendIMPLEMENTATION.md.

Read the existing repository before editing. Preserve completed phases and do not start later phases.
Use the stated technology choices and project structure. Do not use real secrets or commit .env files.

At the end:
1. state the files changed;
2. state how to run the phase locally;
3. provide the exact manual QA steps from the phase;
4. report known limitations/blockers;
5. do not mark the phase complete until its definition of done is met.
```

## Final acceptance checklist

The backend is ready when all items are true:

- [ ] Local setup works with documented commands.
- [ ] Database migrations work on an empty PostGIS database.
- [ ] Chosen US city and 6-12 zones are stored and retrievable.
- [ ] Real historical EIA demand is stored, traceable, and displayed as MW.
- [ ] FortyGuard heatmap requests are submitted asynchronously and safely polled.
- [ ] Completed heatmap GeoJSON is converted into per-zone temperature data.
- [ ] A versioned city-level demand model produces a 12-hour forecast.
- [ ] Zone outputs are explicitly labelled estimated/proxy where appropriate.
- [ ] Each zone has an explainable 0-100 risk score and confidence/data-freshness status.
- [ ] High/critical risk can create a safe recommendation.
- [ ] Human approve/reject/defer decisions are recorded in the audit trail.
- [ ] No backend endpoint controls real grid equipment or leaks secrets.
- [ ] Replay mode can run a complete presentation without external APIs.
- [ ] Manual QA runbook is complete and can be followed independently.
