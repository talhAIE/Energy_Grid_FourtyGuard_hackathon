# Manual QA runbook

This runbook verifies the backend without reading source code. Record every defect with the endpoint, request
body with secrets removed, expected result, actual response/status, and a screenshot or saved response.

## 1. Clean local setup

1. From `backend/`, create and activate a Python 3.12 virtual environment, then run
   `python -m pip install -e ".[dev]"`.
2. Copy `.env.example` to `.env`. Do not commit it.
3. Start PostGIS and the API: `docker compose up --build -d`.
4. Apply schema and seed static geography:

   ```powershell
   docker compose exec api alembic upgrade head
   docker compose exec api python -m app.scripts.seed_city
   docker compose exec api python -m app.scripts.seed_zones
   ```

5. Open `http://127.0.0.1:8000/docs` and use the API base path `/api/v1` below.

## 2. Common checks

1. Call `GET /health`. Expect `200`, no secrets, and `data_mode: "live"` unless replay is enabled.
2. Call `GET /zones`. Expect eight active Houston zones, unique codes, valid geometry, and allocation weights totaling
   `1.0`.
3. Send `GET /audit-events?limit=0`. Expect `422 invalid_request` with a safe validation error, not a server error.
4. Send an `OPTIONS` request from `http://localhost:3000`. Expect the configured CORS origin and only `GET, POST`.

## 3. Live-data workflow

This section needs valid local EIA and FortyGuard keys in `.env`. Keep them out of screenshots and requests.

1. Import a historical EIA range with `POST /data/eia/import`; use a range no longer than 31 days. Expect `201` and
   source `EIA`/area `ERCO`.
2. Read it with `GET /data/demand?start=<same-start>&end=<same-end>&limit=10`. Confirm chronological records,
   MW values, `count <= limit`, and `total >= count`. Repeat with `offset=10` and confirm no overlap.
3. Submit a valid small Houston AOI through `POST /heatmaps/submit`. Expect `202`, a job ID, and no key/raw provider
   response. Submit the identical body again and expect the same ID with `reused: true`.
4. Call `GET /jobs/{job_id}` then `POST /jobs/{job_id}/poll` at controlled intervals. Each poll must return promptly.
   Continue only until the provider completes or a safe failure/timeout status is recorded.
5. After completion, call
   `GET /temperatures?start=<run-time>&end=<run-time-plus-one-hour>&limit=100`. Confirm one normalized entry or
   visible missing marker per overlapping zone; raw map tiles must not appear.
6. Build the feature dataset and train the baseline model using the commands in the README Phase 7/8 sections.
   Confirm `GET /forecast/models/active` returns version/metric metadata but no artifact contents.
7. With complete future demand/temperature inputs, call `POST /forecast/run`. Confirm proxy zone forecasts, bounded
   risk scores, visible freshness/confidence, and no feeder-demand claim.
8. Call `GET /forecasts/latest` and one `GET /forecasts/zones/{zone_id}?limit=10`. Confirm the timeline exposes
   `count`, `total`, `limit`, and `offset` and paging is stable.
9. Call `GET /recommendations?include_inactive=true&limit=10`. For a fresh high/critical forecast, expect a bounded
   human-review recommendation. Submit one `POST /recommendations/{id}/decision`; repeat it and expect `409`.
10. Call `GET /audit-events?limit=100`. Confirm the corresponding import/job/normalization/forecast/recommendation
    events appear. Confirm no payload contains keys, signed URLs, authorization values, or raw provider output.

## 4. Replay workflow (no external keys)

1. Set `APP_ENV=development`, `REPLAY_MODE=true`, and leave `EIA_API_KEY`/`FORTYGUARD_API_KEY` blank. Restart the
   API; migrations and seeded PostGIS geography remain required.
2. Call `POST /demo/load-replay` with no body. Expect `201`, `data_mode: "replay"`, a completed cycle/job, and 96
   zone forecast rows (eight zones across twelve hours).
3. In this order call `GET /health`, `/zones`, `/data/demand?start=<replay-start>&end=<replay-end>`,
   `/temperatures?start=<replay-start>&end=<replay-end>`, `/forecasts/latest`, `/recommendations`,
   `/cycles/{cycle_id}`, and `/audit-events`. Confirm every successful response has `data_mode: "replay"`.
4. Use the Medical Center zone ID from `/zones` to read `/forecasts/zones/{zone_id}`. Confirm its risk progresses
   from `watch` through `high` to final `critical` within the fixture timeline.
5. Call `POST /demo/run-cycle` with no body. Expect an offline completed/reused cycle without EIA/FortyGuard keys.
6. Restart with `REPLAY_MODE=false`. Confirm `POST /demo/load-replay` returns `409 replay_mode_disabled` and the
   live demo-cycle path requires a normal heatmap request body.

## 5. Negative and reliability checks

1. Remove `DATABASE_URL` and call a database-backed route. Expect `503 database_not_configured`, with no connection
   string disclosed. Restore it afterward.
2. Try an invalid datetime, malformed UUID, invalid recommendation decision, and `limit=501`. Expect safe `422`
   validation responses.
3. In a non-development `APP_ENV`, verify zone creation, manual cycle controls, and replay controls return `403`.
4. Temporarily use an invalid FortyGuard key/endpoint in a controlled local environment. Confirm safe provider error
   handling; restore the real local configuration afterward.
5. Repeat an equivalent heatmap/cycle/replay load. Confirm durable IDs are reused where documented and duplicate
   paid submissions, forecasts, recommendations, and decisions do not appear.
