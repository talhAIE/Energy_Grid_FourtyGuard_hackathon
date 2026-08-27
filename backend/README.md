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
