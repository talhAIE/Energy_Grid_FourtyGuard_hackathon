# Energy Grid API

## Phase 0 local setup

1. Create a virtual environment:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

2. Install the project:

   ```powershell
   python -m pip install -e ".[dev]"
   ```

3. Create your local configuration:

   ```powershell
   Copy-Item .env.example .env
   ```

4. Edit `backend/.env` locally. Put your keys after these exact names:

   ```dotenv
   EIA_API_KEY=your_eia_key
   FORTYGUARD_API_KEY=your_fortyguard_key
   ```

   Keep the provided `POSTGRES_*` and `DATABASE_URL` values for a local database.

5. Start the API:

   ```powershell
   python -m uvicorn app.main:app --reload
   ```

6. Open `http://127.0.0.1:8000/docs` and call `GET /api/v1/health`.

## Useful commands

```powershell
python -m ruff check .
python -m uvicorn app.main:app --reload
```

Docker is optional for Phase 0. Once Docker Desktop is installed, start the API container with:

```powershell
docker compose up --build
```

## Phase 1 database setup

Docker Desktop is required only for this local Postgres/PostGIS option. From `backend/`:

```powershell
docker compose up --build -d
docker compose exec api alembic upgrade head
docker compose exec api python -m app.scripts.seed_city
```

Then call `GET /api/v1/health`. Its `dependencies.database` field should be `healthy`.

## Phase 2 zone setup

After the database migration and city seed succeed, seed the eight version-controlled Houston demo zones:

```powershell
docker compose exec api python -m app.scripts.seed_zones
```

Check the result with `GET /api/v1/zones`. The response must contain eight active zones whose
allocation weights total `1.0`. `POST /api/v1/zones` is available in development only and rejects
invalid GeoJSON, zones outside the Houston demo boundary, duplicate codes, overlaps, and active
allocation weights above `1.0`.

## Phase 3 EIA historical-demand import

Phase 3 imports **real hourly balancing-authority demand**, not feeder-level Houston demand. The
default local configuration uses EIA Form 930's ERCOT respondent (`ERCO`) as the city-level demand
proxy. It is explicitly a grid-area series and will be allocated to project zones only in a later phase.

1. Make sure `backend/.env` has your EIA key and the safe default EIA settings from `.env.example`:

   ```dotenv
   EIA_API_KEY=your_eia_key
   EIA_DEMAND_ROUTE=electricity/rto/region-data/data
   EIA_DEMAND_AREA_CODE=ERCO
   EIA_DEMAND_TYPE=D
   ```

2. Start PostGIS, migrate, and seed the configured city once:

   ```powershell
   docker compose up --build -d
   docker compose exec api alembic upgrade head
   docker compose exec api python -m app.scripts.seed_city
   ```

3. Import a hot historical week. The import endpoint and script accept a maximum 31-day range:

   ```powershell
   docker compose exec api python -m app.scripts.import_eia_data --start 2025-08-01T00:00:00Z --end 2025-08-08T00:00:00Z
   ```

   Or use `POST /api/v1/data/eia/import` in `/docs` with:

   ```json
   {
     "start": "2025-08-01T00:00:00Z",
     "end": "2025-08-08T00:00:00Z"
   }
   ```

4. Query stored records with `GET /api/v1/data/demand`, passing the same `start` and `end` as ISO-8601
   query parameters. The response contains `demand_mw`, UTC timestamps, source `EIA`, source area `ERCO`,
   and an `is_actual` flag.

5. Run the same import again. It should report `created=0` and skipped duplicates rather than store the
   same source-area/timestamp record twice.

## Phase 4 FortyGuard heatmap submission

Phase 4 submits a heatmap task and returns after FortyGuard acknowledges its `activity_id`. It does
**not** wait for the final heatmap or poll task status; that background workflow is Phase 5.

1. In your ignored `backend/.env`, keep the FortyGuard key server-side and configure the request limits:

   ```dotenv
   FORTYGUARD_API_KEY=your_fortyguard_key
   FORTYGUARD_DEFAULT_GRANULARITY=80
   FORTYGUARD_REQUEST_TIMEOUT_SECONDS=30
   FORTYGUARD_MAX_HEATMAP_AREA_SQ_MI=50
   FORTYGUARD_MAX_FORECAST_HOURS=12
   ```

   Set the area limit lower if the plan attached to your real key permits less than 50 square miles.

2. Migrate and seed the city boundary before submitting a map:

   ```powershell
   docker compose up --build -d
   docker compose exec api alembic upgrade head
   docker compose exec api python -m app.scripts.seed_city
   ```

3. Use `POST /api/v1/heatmaps/submit` in `/docs`. This example AOI is a small rectangle inside the
   approximate Houston demo boundary; date/time inputs are interpreted as UTC:

   ```json
   {
     "polygon_aoi": {
       "type": "FeatureCollection",
       "features": [
         {
           "type": "Feature",
           "properties": {},
           "geometry": {
             "type": "Polygon",
             "coordinates": [[
               [-95.70, 29.70], [-95.69, 29.70],
               [-95.69, 29.71], [-95.70, 29.71],
               [-95.70, 29.70]
             ]]
           }
         }
       ]
     },
     "date_time": {
       "start_date": "2025-08-01",
       "start_time": "12:00",
       "filter_type": 1
     },
     "granularity": 80,
     "analytic_type": "tcm"
   }
   ```

4. Expected response: HTTP `202`, an internal `job_id`, `status: "submitted"`, and a provider
   `activity_id`. The response never contains your API key or raw provider headers.

5. Submit the exact same JSON again. Expected: the same `job_id` and `activity_id`, with
   `reused: true`; no second FortyGuard task should be submitted.

6. Try a non-closed polygon, an AOI outside the demo city, `granularity: 70`, an unsupported analytic
   type, or an AOI larger than the configured area limit. Expected: a clear `400` response and no
   FortyGuard request.

## Phase 5 FortyGuard one-shot polling

Phase 5 uses **client-triggered polling**, not a Redis queue or a background worker. After a successful
submission, call the poll route about every five seconds until the stored job becomes `completed`, `failed`,
or `timed_out`. Each request makes only one FortyGuard status call and returns immediately.

1. Make sure `FORTYGUARD_POLL_SECONDS=5` and `FORTYGUARD_MAX_POLL_SECONDS=600` are present in
   `backend/.env`. The latter is a hard total polling window measured from job submission time.

2. Migrate the new polling fields after starting your PostGIS database:

   ```powershell
   docker compose exec api alembic upgrade head
   ```

3. Submit a valid map with `POST /api/v1/heatmaps/submit`, then copy only the returned internal `job_id`.

4. Call `POST /api/v1/jobs/{job_id}/poll` every five seconds. It returns stored state, for example:

   ```json
   {
     "data": {
       "job_id": "your-internal-job-id",
       "status": "processing",
       "provider_status": "processing",
       "activity_id": "fortyguard-activity-id",
       "poll_attempts": 1,
       "raw_response_available": true
     }
   }
   ```

5. Use `GET /api/v1/jobs/{job_id}` between polls to read the persisted state without making an external
   request. It intentionally never returns the raw heatmap payload, signed URLs, headers, or credentials.

6. A `404` immediately after task submission is treated as temporary: the job remains `processing` with
   `provider_status: "not_found"`; wait five seconds and poll again. `completed`/`succeeded` become
   internal `completed`; `failed`/`error` become internal `failed`. A job is changed to `timed_out` if it
   is polled after its configured maximum window.

The backend saves only a scrubbed, size-limited provider response/summary for future normalization. It does
not log or expose API keys, signed URLs, or oversized heatmap payloads.

## Phase 6 heatmap normalization and zone temperatures

When `POST /api/v1/jobs/{job_id}/poll` first receives a completed/succeeded provider status, the backend
automatically parses the returned `data.result.map_data` GeoJSON and writes zone-temperature observations.
No extra provider request is made.

- **Assignment rule:** each valid heat tile is assigned to the active zone containing its centroid. If a
  centroid lies exactly on shared boundaries, the first zone code in alphabetical order wins. This avoids
  double-counting a tile.
- **Missing data:** every active zone that overlaps the requested heatmap AOI receives a record. Zones with
  no assigned tiles are stored as `data_status: "missing"` with null statistics—not zero temperature.
- **Traceability:** each record keeps its `source_run_id`, source-retrieval time, tile count, requested
  observation time, and `is_forecast` flag.

1. Run the latest migration and seed active zones before submitting a heatmap:

   ```powershell
   docker compose exec api alembic upgrade head
   docker compose exec api python -m app.scripts.seed_city
   docker compose exec api python -m app.scripts.seed_zones
   ```

2. Submit a valid `tcm` heatmap with an AOI overlapping one or more demo zones. Poll the job every five
   seconds until its status is `completed`.

3. Query the stored temperature timeline with `GET /api/v1/temperatures`:

   ```text
   /api/v1/temperatures?start=2025-08-01T00:00:00Z&end=2025-08-02T00:00:00Z
   ```

   Add `zone_id=<uuid>` to select one zone, or `include_missing=false` to return only available values.

4. Confirm an available record contains `mean_c`, `min_c`, `max_c`, `stddev_c`, a positive `tile_count`,
   and `source_run_id`. A missing record must have `data_status: "missing"`, `tile_count: 0`, and null
   statistics.

## Phase 7 feature dataset and Cooling Degree Hours

Phase 7 builds a versioned, city-level model dataset from persisted EIA demand and the zone temperatures
created in Phase 6. It is intentionally a script rather than an API route: building a dataset is an
explicit development/training step, not a request that a dashboard should run.

- Demand and temperatures are matched at the same UTC timestamp. `period_local` converts that instant to
  `DEMO_TIMEZONE` (`America/Chicago` by default) for calendar features and daylight-saving-time safety.
- `city_temperature_c` is an allocation-weighted mean of the available active zones. The result carries
  `temperature_coverage_weight`, so partial coverage is visible.
- Cooling Degree Hours are `max(0, city_temperature_c - COOLING_BASE_TEMPERATURE_C)`. The default baseline
  is `18` Celsius and can be changed only through local configuration.
- Missing temperatures are never interpolated, filled forward, or converted to zero. Such rows have null
  temperature/CDH and a `missing_temperature` quality status.

1. Complete the Phase 1, 3, and 6 database/manual QA prerequisites so there are seeded active zones,
   persisted ERCOT demand, and zone-temperature observations for the requested period.

2. In `backend/.env`, keep or adjust the safe defaults:

   ```dotenv
   COOLING_BASE_TEMPERATURE_C=18
   FEATURE_DATASET_MAX_RANGE_DAYS=366
   FEATURE_DATASET_DIR=app/data/generated/features
   ```

3. Build a defined historical range (up to the configured maximum):

   ```powershell
   python -m app.scripts.build_feature_dataset --start 2025-08-01T00:00:00Z --end 2025-08-08T00:00:00Z
   ```

   When using the optional local Docker API service, run the same command inside it with
   `docker compose exec api`. The command writes a versioned `.csv` and matching `.quality.json` report to
   `FEATURE_DATASET_DIR`; generated files are ignored by Git.

4. Read the [feature dataset contract](docs/feature-dataset-contract.md) before Phase 8 model work. It
   defines all fields and the allowed quality statuses.

5. Manual QA: check CDH at 16, 18, 20, 25, and 30 Celsius with the 18 Celsius baseline; expected values
   are 0, 0, 2, 7, and 12. Also inspect rows around a Houston daylight-saving transition and confirm the
   quality report clearly counts partial/missing temperature rows.

## Phase 8 baseline city-demand model

Phase 8 uses a transparent ordinary least-squares regression to estimate **city/grid-area demand**, not
feeder-level or zone-level demand. It combines Cooling Degree Hours, local calendar fields, and actual demand
from exactly one hour and 24 hours earlier. The model never trains on partial/missing-temperature rows and
never fills missing values.

1. Install the updated project dependencies after pulling Phase 8:

   ```powershell
   python -m pip install -e ".[dev]"
   ```

2. Apply the model-version migration after your PostGIS database is available:

   ```powershell
   alembic upgrade head
   ```

3. Build a Phase 7 feature CSV with a sufficiently long complete-temperature history. By default, the model
   needs at least 72 training rows plus a later validation period after 1-hour/24-hour lags are formed.

4. Train and activate the model using the exact generated CSV path:

   ```powershell
   python -m app.scripts.train_model --dataset .\app\data\generated\features\features-v1-your-version.csv
   ```

   The model JSON and validation-prediction CSV are written to `MODEL_ARTIFACT_DIR` (default:
   `app/data/generated/models/`) and are ignored by Git. The validation CSV is the manual-QA chart/export.

5. Inspect the active model and metrics with `GET /api/v1/forecast/models/active`.

6. Call `POST /api/v1/forecast/run` with `{}` to select the next usable future temperature time, or supply a
   specific time:

   ```json
   {
     "forecast_for": "2025-08-08T12:00:00Z"
   }
   ```

   The route returns `estimate_type: "estimate"`, the explicit model version, validation-safe input details,
   and predicted demand in MW. It also persists the corresponding Phase 9 zone proxy forecasts. It returns a
   clear error rather than guessing if the model artifact, complete zone temperatures, or 1-hour/24-hour demand
   lags are unavailable.

7. Read the [baseline model contract](docs/baseline-model-contract.md) before using the metrics. It documents
   the chronological split, feature eligibility, artifact format, and forecast safety rules.

## Phase 9 zone demand allocation and risk scoring

Phase 9 converts the guarded city-level estimate into one **proxy** estimate per active zone. It never claims
to measure feeder or zone load. The baseline allocation uses the configured zone allocation weight; the final
proxy allocation adjusts that share by the zone's heat anomaly relative to the allocation-weighted city
temperature, then normalizes all zones so their predicted MW total approximately equals the city estimate.

`POST /api/v1/forecast/run` now creates the zone set after a successful city estimate. Its response contains
`zone_forecast_count` and `zone_forecasts_reused`; an equivalent model/time set is reused rather than changed.

- `GET /api/v1/forecasts/latest` returns the most recently generated set for all zones.
- `GET /api/v1/forecasts/zones/{zone_id}` returns one zone's stored timeline. Optional `start` and `end` are
  inclusive ISO-8601 UTC bounds; an omitted range defaults to the recent week plus the next day.

Each stored result includes the temperature, heat anomaly, exact one-hour temperature ramp when available,
baseline and proxy MW, uplift percentage, risk score/label, confidence, freshness status, allocation weight,
and structured calculation evidence. Risk is deterministic: normalized demand uplift (45%), heat anomaly
(30%), rising temperature (15%), and an uncertainty penalty (10%) are passed through a documented logistic
formula. Scores use `low` (0-39), `watch` (40-64), `high` (65-79), and `critical` (80-100).

1. Apply the new migration after the Phase 8 model is available:

   ```powershell
   alembic upgrade head
   ```

2. Ensure a selected future time has complete active-zone temperature coverage and real EIA demand exactly one
   and 24 hours earlier. Add an exact prior-hour zone temperature when you want the temperature-ramp input.

3. Run the forecast, then call `GET /api/v1/forecasts/latest`. Confirm there is one record per active zone, all
   results contain `estimate_type: "proxy"`, and `risk_score` is numeric and within 0-100.

4. Sum `predicted_mw` across the latest set. It should equal the city forecast within normal three-decimal
   rounding. Confirm every record retains its allocation weight and model version.

5. Compare two zones with different temperatures. The hotter-than-city zone should receive a positive heat
   anomaly and a higher heat-adjusted proxy allocation than its baseline share; the explanation object exposes
   the multiplier and normalized inputs used to calculate it.

6. Omit the prior-hour temperature for one zone or use a stale source retrieval time. Confirm the result remains
   explicitly visible with a lower confidence and a larger uncertainty penalty; partial/missing same-time
   temperature coverage must instead stop forecast creation with a readable error.

## Phase 10 recommendations and human decisions

Phase 10 is a decision-support layer only. It never sends a grid command, dispatches generation, changes a
switch, or contacts a customer. After `POST /api/v1/forecast/run` produces the zone forecasts, the backend
evaluates each one against explicit guardrails and returns its `recommendation_eligibility` reason code.

A recommendation is created only when the forecast is a future proxy estimate, its temperature data is fresh,
its confidence meets `RECOMMENDATION_MIN_CONFIDENCE`, and its risk score meets
`RECOMMENDATION_MIN_RISK_SCORE` (default: 65 / `high`). Stale or low-confidence forecasts create no action
recommendation. Their reason is returned by the forecast response and recorded in the audit trail.

The fixed action catalogue is deliberately bounded:

- `watch`: monitor and schedule a re-check.
- `high`: verify reserve capacity and prepare voluntary demand-response options.
- `critical`: escalate to the duty operator and review the approved response plan.

Recommendations expire at the earlier of `RECOMMENDATION_EXPIRY_MINUTES` (default 120 minutes) and their
forecast time. A newer zone forecast supersedes an older pending recommendation for that zone. A human can make
exactly one immutable `approved`, `rejected`, or `deferred` decision; recording a decision does not execute the
proposed action.

1. Apply the recommendation migration:

   ```powershell
   alembic upgrade head
   ```

2. Generate a future high/critical, fresh, sufficiently confident zone forecast with
   `POST /api/v1/forecast/run`. Confirm the response reports `recommendations_created_count` and an `eligible`
   entry for the qualifying zone.

3. Call `GET /api/v1/recommendations`. It returns pending recommendations by default, including structured
   reason/evidence, expiry, risk, action code, and a plain safety boundary. Add `include_inactive=true` to read
   prior decisions, expired items, or superseded recommendations; use `status=<value>` to filter a known state.

4. Record a test decision with `POST /api/v1/recommendations/{recommendation_id}/decision`:

   ```json
   {
     "decision": "approved",
     "operator_name": "Demo Operator",
     "note": "Reviewed the forecast evidence."
   }
   ```

   Expected: a `201` response containing the immutable decision record. Repeating the request for the same
   recommendation returns `409 recommendation_not_decidable`; no operational action is performed.

5. Use a stale or low-confidence zone forecast. Confirm `recommendations_created_count` is zero for that zone,
   `recommendation_eligibility` exposes `stale_temperature_data` or `insufficient_confidence`, and no pending
   recommendation appears in the list.

## Phase 11 manually advanced pipeline and safeguards

Phase 11 adds durable orchestration without an always-on worker. A manual cycle submits or reuses one heatmap
task, performs **at most one** provider status poll, persists the result, and returns promptly. Repeating the
same request or calling the cycle advance endpoint later resumes from stored state; it does not submit another
equivalent FortyGuard task.

Development/test-only controls:

- `POST /api/v1/cycles/run` starts or resumes a manual cycle.
- `POST /api/v1/cycles/{cycle_id}/advance` makes the next bounded advance/poll.
- `GET /api/v1/cycles/{cycle_id}` reads persisted cycle/job state without contacting FortyGuard.
- `POST /api/v1/demo/run-cycle` uses the same protected path for local demo work. Replay fixtures are added in
  Phase 12, so this currently uses the supplied live heatmap request.

Each start request has this shape:

```json
{
  "heatmap": {
    "polygon_aoi": { "type": "FeatureCollection", "features": [] },
    "date_time": { "start_date": "2026-08-29", "start_time": "12:00", "filter_type": 1 },
    "granularity": 80,
    "analytic_type": "tcm"
  }
}
```

Use a valid Houston AOI as shown in the Phase 4 example; the shortened empty FeatureCollection above is only the
request envelope. Once the provider job completes and Phase 6 normalization succeeds, the same cycle runs the
city forecast, zone proxy-risk allocation, and guarded recommendations. A cycle exposes `data_freshness_status`
as `fresh`, `stale`, or `unavailable`, so dashboards can avoid acting on stale outputs.

Operational safeguards:

- `PIPELINE_MAX_POLL_ATTEMPTS=120` stops a cycle from issuing unlimited status polls.
- Provider failures, timeouts, normalization failures, and unavailable forecast inputs become persisted cycle
  `failed` or `blocked` states with audit events.
- `FORTYGUARD_DAILY_SUBMISSION_LIMIT=24` is a conservative local task-count budget before a new potentially
  billed submission. Set it to `0` only when intentionally disabling the guard in local configuration.
- Database uniqueness links one cycle to one integration job; the existing request hash plus zone/recommendation
  uniqueness rules prevent duplicate jobs, forecasts, or active recommendations when requests overlap.

1. Apply the migration:

   ```powershell
   alembic upgrade head
   ```

2. In development, call `POST /api/v1/cycles/run` with the valid Phase 4 heatmap body nested under `heatmap`.
   Save the returned cycle ID. The first response should be `submitted` or `processing` and return immediately.

3. Call `POST /api/v1/cycles/{cycle_id}/advance` about every five seconds. Use
   `GET /api/v1/cycles/{cycle_id}` between calls to inspect state without another provider request.

4. On successful completion, confirm `status: "completed"`, a positive `zone_forecast_count`, the intended
   `recommendation_count`, and visible `data_freshness_status`. Confirm the normal forecast/recommendation APIs
   contain the same downstream results.

5. Trigger the exact same cycle body while the original is active. Confirm the existing job/cycle is reused and
   the provider does not receive a second submission. Lower the local poll-attempt or daily-submission limit only
   for controlled QA to confirm the safe `failed`/budget-blocked outcomes.

## Phase 12 offline replay mode

Phase 12 provides a deterministic, no-network Houston demonstration for development and test environments. The
fixture at `app/data/replay/houston_watch_to_critical.json` contains no API keys, authorization headers, signed
URLs, customer data, or raw provider response. It deliberately moves the Medical Center zone from `watch` to
`high` and then `critical` over twelve hourly forecast slots.

Set the following only in ignored local `backend/.env`:

```dotenv
APP_ENV=development
REPLAY_MODE=true
EIA_API_KEY=
FORTYGUARD_API_KEY=
```

Then apply migrations and load the scenario:

```powershell
alembic upgrade head
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/v1/demo/load-replay
```

The loader writes ordinary city, zone, demand, heatmap-run, temperature, zone-forecast, recommendation, and
pipeline-cycle records. It does not instantiate either external client. Repeating the request safely reuses
records for the current replay slots where the existing uniqueness rules permit it.

- `POST /api/v1/demo/load-replay` creates/reuses the complete twelve-hour fixture and returns its final cycle/job.
- `POST /api/v1/demo/run-cycle` has no body in replay mode and loads/reuses the same offline cycle.
- Both routes are limited to `development` and `test`; `/demo/load-replay` returns `409` until
  `REPLAY_MODE=true` is set.
- Dashboard-facing responses include `data_mode: "replay"` when replay is enabled and `data_mode: "live"`
  otherwise, including health, zones, demand, temperatures, forecasts, recommendations, jobs, heatmaps, and cycles.

After loading, use `GET /api/v1/zones`, `GET /api/v1/data/demand`, `GET /api/v1/forecasts/latest`,
`GET /api/v1/recommendations`, and `GET /api/v1/cycles/{cycle_id}` with the returned ID. Each should return
coherent replay records and `data_mode: "replay"`. Replay audit events are persisted; Phase 13 adds the dedicated
audit-history read API.

No completed real-provider capture is stored in this repository, so the committed fixture is candidly labeled a
scrubbed deterministic demonstration dataset. Before claiming production provenance, replace its numeric values
with an approved scrub of completed FortyGuard/EIA results while retaining the no-secret/no-signed-URL constraint.
