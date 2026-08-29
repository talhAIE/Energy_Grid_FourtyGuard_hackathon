# Energy Grid API contract

Base URL: `http://127.0.0.1:8000/api/v1` in local development. Interactive OpenAPI documentation is available at
`/docs`; the JSON contract is `/openapi.json`.

## Cross-cutting rules

- Every successful dashboard-facing response includes `data_mode: "live" | "replay"` and a `data` field.
- Zone demand and risk values are always `estimate_type: "proxy"`; they are not feeder measurements.
- Recommendation endpoints record human decisions only. No endpoint controls grid equipment, markets, customers,
  or devices.
- List responses provide `count` (items returned), `total` (items matching filters), `limit`, and `offset` where
  pagination applies. `limit` is 1–500; `offset` is zero-based.
- ISO-8601 UTC timestamps are recommended. Date-range reads are bounded to protect the API.
- Safe errors use `detail.code` and `detail.message`. Request validation errors additionally contain a safe
  `detail.errors` array with location/message/type, never the submitted input value.

Example error:

```json
{
  "detail": {
    "code": "invalid_request",
    "message": "Request validation failed.",
    "errors": [{"location": ["query", "limit"], "message": "Input should be greater than or equal to 1", "type": "greater_than_equal"}]
  }
}
```

## Read routes

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Service/dependency status and replay disclosure |
| GET | `/zones` | Map-ready configured zones; `active_only=true` by default |
| GET | `/data/demand` | Stored hourly demand; required `start`, `end`; supports `limit`, `offset` |
| GET | `/temperatures` | Stored zone temperatures; required `start`, `end`; supports `zone_id`, `include_missing`, `limit`, `offset` |
| GET | `/forecast/models/active` | Active city-baseline model metadata |
| GET | `/forecasts/latest` | Latest all-zone proxy-risk set |
| GET | `/forecasts/zones/{zone_id}` | Bounded zone timeline; supports `start`, `end`, `limit`, `offset` |
| GET | `/recommendations` | Pending items by default; supports `status`, `include_inactive`, `limit`, `offset` |
| GET | `/jobs/{job_id}` | Stored heatmap job state only |
| GET | `/cycles/{cycle_id}` | Stored pipeline-cycle state only |
| GET | `/audit-events` | Redacted audit history; supports event/entity/time filters and pagination |

`/zones` and `/forecasts/latest` are intentionally non-paginated: each returns one small, complete map/forecast set.

Example latest forecast response (fields shortened):

```json
{
  "data_mode": "replay",
  "data": {
    "forecast_for": "2026-08-29T12:00:00Z",
    "model_version": "replay-houston-baseline-v1",
    "estimate_type": "proxy",
    "forecasts": [{
      "zone_id": "00000000-0000-0000-0000-000000000000",
      "predicted_mw": 8292.114,
      "risk_score": 91,
      "risk_level": "critical",
      "confidence": "high",
      "data_freshness_status": "fresh"
    }]
  }
}
```

Example audit page:

```json
{
  "data_mode": "replay",
  "data": [{
    "event_type": "replay.loaded",
    "entity_type": "pipeline_cycle",
    "entity_id": "00000000-0000-0000-0000-000000000000",
    "payload": {"fixture_name": "houston_watch_to_critical.json", "network_calls": 0},
    "created_at": "2026-08-29T12:00:00Z"
  }],
  "count": 1,
  "total": 1,
  "limit": 100,
  "offset": 0
}
```

Audit payloads are redacted/truncated on read for credential-like keys, nested content, long strings, and large
arrays. They must not be used to retrieve provider output.

## Write and control routes

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/data/eia/import` | Import a bounded historical EIA range; needs live EIA configuration |
| POST | `/heatmaps/submit` | Submit one asynchronous FortyGuard heatmap job; needs live FortyGuard configuration |
| POST | `/jobs/{job_id}/poll` | One provider poll only; never waits for completion |
| POST | `/forecast/run` | Create/reuse city and zone proxy forecast for a supplied future time |
| POST | `/recommendations/{recommendation_id}/decision` | Record exactly one immutable human decision |
| POST | `/cycles/run` | Development/test-only live manual pipeline trigger |
| POST | `/cycles/{cycle_id}/advance` | Development/test-only bounded cycle advance |
| POST | `/demo/load-replay` | Development/test-only no-network fixture loader; requires `REPLAY_MODE=true` |
| POST | `/demo/run-cycle` | Development/test-only replay trigger with no body when replay is enabled |
| POST | `/zones` | Development/test-only zone creation with geometry/allocation validation |

Representative request bodies:

```json
// POST /data/eia/import
{"start": "2025-08-01T00:00:00Z", "end": "2025-08-08T00:00:00Z"}

// POST /forecast/run
{"forecast_for": "2026-08-29T12:00:00Z"}

// POST /recommendations/{recommendation_id}/decision
{"decision": "approved", "operator_name": "Demo Operator", "note": "Reviewed forecast evidence."}
```

For a heatmap request, use the complete validated Houston FeatureCollection from the Phase 4 section of the
README. Never put either API key in a request body. Poll returned jobs/cycles later rather than holding a browser
request open.

## Browser access and CORS

`CORS_ALLOWED_ORIGINS` is a comma-separated allowlist. The local default permits only
`http://localhost:3000` and `http://127.0.0.1:3000`; wildcard origins and credentials are intentionally disabled.
Set the production frontend’s exact HTTPS origin before deployment, for example:

```dotenv
CORS_ALLOWED_ORIGINS=https://dashboard.example.com
```

The API permits browser `GET` and `POST` requests with `Content-Type`. Add a method/header only after the
corresponding API route and frontend need have been reviewed.
