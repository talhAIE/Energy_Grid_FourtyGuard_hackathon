# FortyGuard Temperature API - Integration Reference

This is a practical API guide for the **Energy Grid Heat-Demand Forecaster**. It consolidates the public documentation as reviewed on 24 August 2026. Keep the linked official pages as the source of truth because endpoint behavior, plan access, and limits can change.

## Executive summary

- Base URL: `https://api.fortyguard.com`
- Auth: API key in every request: `api-key: YOUR_API_KEY`
- Main pattern: submit an asynchronous analysis task -> receive `activity_id` -> poll `GET /v1/status/{activity_id}` -> consume endpoint-specific result.
- API documentation identifies five documented analysis POST endpoints, one task-status GET endpoint, and two credit-usage POST endpoints. A presentation slide describes “six endpoints” by counting the five analyses plus status; use the individual endpoint paths below when implementing.
- For Energy Grid, `POST /v1/heatmap` is the essential endpoint. It returns GeoJSON temperature tiles and supports a forecast window up to 12 hours ahead.
- Current documented regional coverage is **United States only**. Design the demo around a US city.

Official starting points: [Introduction](https://docs-api.fortyguard.com/) · [Quickstart](https://docs-api.fortyguard.com/docs/quickstart) · [Authentication](https://docs-api.fortyguard.com/docs/authentication) · [Limitations](https://docs-api.fortyguard.com/docs/limitations) · [Release notes](https://docs-api.fortyguard.com/docs/release-notes)

## Credentials and security

Create a key in the FortyGuard dashboard, then put it in a local, git-ignored `.env` file:

```dotenv
FORTYGUARD_API_KEY=fg_live_replace_me
FORTYGUARD_BASE_URL=https://api.fortyguard.com
```

Send it only as a server-side HTTP header:

```http
api-key: YOUR_API_KEY
Content-Type: application/json
```

Do not expose the key in browser code, commit it, paste it into a ticket, or log it. Authentication is API-key based; no OAuth or token exchange is needed. [Authentication](https://docs-api.fortyguard.com/docs/authentication)

Hackathon material supplied with this project says the hackathon key has 2,000,000 credits valid for five weeks and Premium-level access. Confirm the actual plan and remaining balance using the dashboard/usage endpoint before relying on a Premium feature.

## Plans and constraints

| Capability | Basic | Premium | Startup |
| --- | --- | --- | --- |
| Credits | 1,000,000/month | 5,000,000/month | 1,000,000 one-time |
| Heatmap max area | 10 mi2 | 50 mi2 | 10 mi2 |
| Map statistics | Yes | Yes | Yes |
| Environmental parameters | Up to 3/request | Full access | Up to 3/request |
| Satellite segmentation | No | Yes | No |
| Streetview segmentation | No | Yes | No |
| Heat Intelligence reports | No | Yes | No |
| Coverage | US only | US only | US only |

The documented Startup access window is six months; Basic/Premium renew monthly. Credits are charged only after a task completes successfully. Failed and invalid (`400`) tasks are not charged, and unused credits do not roll over. [Known limitations](https://docs-api.fortyguard.com/docs/limitations)

## Universal asynchronous workflow

```text
POST analysis request
        |
        +--> 200/202-style submission body with data.activity_id
                                         |
                                         v
                       GET /v1/status/{activity_id}
                         |       |          |
                   Processing   Completed   Failed/Error
                      retry        consume     stop + record ID
```

Use these implementation rules:

- Persist the `activity_id` as soon as it is returned.
- Poll at a bounded interval such as 3-5 seconds, with backoff for `429`/transient errors.
- A short-lived `404` immediately after submission can be normal. Retry it rather than marking the task failed.
- Match terminal status case-insensitively. Treat `completed` and `succeeded` as success; `failed` and `error` as terminal failure.
- Use a generous end-to-end timeout. Heat Intelligence reports may legitimately exceed 120 seconds.
- Stop polling on any terminal state. Do not keep sending requests after completion.
- Cache completed requests by inputs to avoid duplicate work and credit use.

Typical responses/statuses: `400`/`422` invalid request, `401` missing or invalid key, `403` insufficient plan, `404` activity not found/temporarily unavailable, `429` rate limit, and `500` processing error. [Quickstart](https://docs-api.fortyguard.com/docs/quickstart)

## Endpoint catalogue

| Endpoint | Plan | Main input | Completed result | Energy Grid role |
| --- | --- | --- | --- | --- |
| `POST /v1/heatmap` | Basic, Premium, Startup | Polygon AOI, time window, granularity | GeoJSON tiles + map statistics | **Primary temperature/forecast source** |
| `POST /v1/env_params` | Basic, Premium, Startup | Point, temperature, time window | Environmental time series + solar data | Optional model enrichment |
| `POST /v1/satellite` | Premium | Point, time window, granularity | Base64 imagery + land-cover segments | Optional exposure explanation |
| `POST /v1/streetview` | Premium | Point and camera angles | Base64 images + segment coverage | Optional local explainability |
| `POST /v1/heat_intelligence` | Premium | Point, temperature, date, analysis list | Temporary PDF download link | Optional evidence report, not primary pipeline |
| `GET /v1/status/{activity_id}` | Basic, Premium, Startup | Activity ID | State plus completed result | Required for all jobs |
| `POST /v1/system/fetch-api-key-usage` | documented system endpoint | API key/header | Current cycle usage | Pre-demo credit health |
| `POST /v1/system/fetch-api-key-custom-usage` | documented system endpoint | API key/header and date range | Usage for custom period | Cost/usage analysis |

The two usage paths are recorded in the [release notes](https://docs-api.fortyguard.com/docs/release-notes). Verify their exact request schema in the live dashboard/documentation before coding because the public search index does not expose it.

## 1. Create Heatmap - `POST /v1/heatmap`

Official reference: [Create Heatmap](https://docs-api.fortyguard.com/docs/create-heatmap)

Produces a GeoJSON FeatureCollection of thermal tiles for a polygon area plus aggregate statistics. This is the correct primary endpoint for Energy Grid.

### Required body

| Field | Type | Notes |
| --- | --- | --- |
| `polygon_aoi` | GeoJSON `FeatureCollection` | Must contain a closed `Polygon`; first/last coordinate match |
| `date_time.start_date` | `YYYY-MM-DD` | Supported from 2019-01-01 to now + 12 hours |
| `date_time.filter_type` | number | `1` single hour, `2` range of hours, `3` single day, `4` range of days up to one month |
| `granularity` | number | `60`, `80`, or `100` metres |

Additional time fields:

- Filter `1`: also send `start_time` (`HH:MM`); end is calculated.
- Filter `2`: send `start_time` and `end_time`.
- Filter `3`: only `start_date` is needed.
- Filter `4`: send `start_date` and `end_date`.

### Optional analysis fields

| Field | Values | Meaning |
| --- | --- | --- |
| `analytic_type` | `tcm` (default) | Temperature snapshot; values/statistics in Celsius |
|  | `time_of_measure` | Hour of peak temperature (UTC) |
|  | `exceedance` | Hours crossing a threshold |
|  | `persistence` | Longest continuous threshold exceedance |
| `threshold` | number in Celsius | Defaults to `30`; used only for `exceedance`/`persistence` |
| `direction` | `above` (default), `below` | Threshold direction |

`time_of_measure`, `exceedance`, and `persistence` use `hour` units. `tcm` uses Celsius.

### Minimal Energy Grid request

```python
import os
import requests

url = "https://api.fortyguard.com/v1/heatmap"
headers = {
    "api-key": os.environ["FORTYGUARD_API_KEY"],
    "Content-Type": "application/json",
}

payload = {
    "polygon_aoi": {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"zone_id": "zone-4"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [-74.0170, 40.7050], [-74.0030, 40.7050],
                    [-74.0030, 40.7180], [-74.0170, 40.7180],
                    [-74.0170, 40.7050]
                ]],
            },
        }],
    },
    "date_time": {"start_date": "2026-08-24", "start_time": "14:00", "filter_type": 1},
    "granularity": 80,
    "analytic_type": "tcm",
}

response = requests.post(url, headers=headers, json=payload, timeout=30)
response.raise_for_status()
activity_id = response.json()["data"]["activity_id"]
```

Expected submission shape:

```json
{
  "error": false,
  "status_code": 200,
  "message": "Heatmap Submitted Successfully",
  "data": { "activity_id": "uuid" }
}
```

On completion, read `data.result.map_data` (GeoJSON thermal tiles) and `data.result.stats_data` (minimum/mean/maximum, standard deviation, distributions, and frequency data). Store the requested time and return time alongside the result; forecast work must never silently mix up request time, source time, and retrieval time.

## 2. Environmental Parameters - `POST /v1/env_params`

Official reference: [Environmental Parameters](https://docs-api.fortyguard.com/docs/environmental-parameters)

Returns environmental inputs that can complement temperature-only load modelling: heat index, apparent temperature, humidity, wet-bulb temperature, precipitation, cloud cover, AQI subindices, methane, CO2, and clear-sky solar irradiance (`GHI`, `DNI`, `DHI`). Basic/Startup plans allow up to three selectable parameters; Premium has full access.

Required fields: `latitude`, `longitude`, `temperature` (Celsius), and `date_time.start_date` + `filter_type`. Its documented filter types are `1` single hour, `2` range of hours, and `3` single day. Filters 1/2 require `start_time`; 2 also needs `end_time`.

Use it after a heatmap result supplies a zone/point temperature. In the prototype, treat this as optional enrichment because the public limitations page says its date/time should match the heatmap for the same location/time. Do not assume it creates a separate 12-hour forecast beyond what the heatmap endpoint documents.

Completed result:

```text
data.result.metadata          timezone, timestamps, time range
data.result.locations[]       point, elevation, temperature
data.result.locations[].parameters
data.result.locations[].solar_irradiance
```

## 3. Satellite View Segmentation - `POST /v1/satellite`

Official reference: [Satellite View Segmentation](https://docs-api.fortyguard.com/docs/satellite-view-segmentation)

Premium-only. Required body: `sat.latitude`, `sat.longitude`, `date_time`, and `granularity` (`60`, `80`, `100`). The date must be from 2019-01-01 to current time + 5 hours and should match the heatmap context.

Completed result contains coordinates, `orignal_image` (the documentation's field spelling), `image_year`, and `segmentation` containing segment coverage, legend, mask image, processing time, dimensions, and request ID. Images are Base64; add `data:image/png;base64,` if a MIME prefix is absent.

Energy Grid use: optional “why is this zone exposed?” evidence (building/tree/road/other shares). It should not block the primary forecast.

## 4. Street View Segmentation - `POST /v1/streetview`

Official reference: [Street View Segmentation](https://docs-api.fortyguard.com/docs/street-view-segmentation)

Premium-only. Required body: `latitude`, `longitude`, `vertical_angle`, `horizontal_angle` (0-360), and `back_view` boolean. Completed result has `coordinates` and `front`; the latter includes Base64 `original_image`, `segmented_image`, `segments`, `image_legend`, and `image_date`.

Energy Grid use: an optional visual proof of shade, road, vegetation, and building exposure around a high-risk asset. It has no role in the core demand calculation.

## 5. Heat Intelligence - `POST /v1/heat_intelligence`

Official reference: [Heat Intelligence](https://docs-api.fortyguard.com/docs/heat-intelligence)

Premium-only. Required body: `latitude`, `longitude`, `temperature` (Celsius), `date` (`YYYY-MM-DD`), and `analysis` array. Allowed analysis values are:

```json
["geographic", "environmental", "urban", "events", "anthropogenic"]
```

This creates a multi-dimensional PDF report. The current endpoint page says a completed status response includes `data.result.download_link`, a temporary signed URL. Download it immediately, do not log/share the complete signed URL, then stop polling.

### Documentation inconsistency to handle safely

The separate [Check Status](https://docs-api.fortyguard.com/docs/check-status) page still describes the report as a streamed-PDF status response, while the newer Heat Intelligence page and release notes say the status response returns JSON with a temporary `download_link`. For production-quality code:

1. Prefer the endpoint-specific Heat Intelligence guidance (`download_link`).
2. Inspect response `Content-Type`; if JSON, safely extract `download_link`; if PDF, stream it to a file.
3. Never assume one response shape without validating it in a test request.

## 6. Check Status - `GET /v1/status/{activity_id}`

Official reference: [Check Status](https://docs-api.fortyguard.com/docs/check-status)

All analysis requests use this unified task-status endpoint. Required path parameter: `activity_id`. Supply the `api-key` header.

Example polling helper:

```python
import time
import requests

def wait_for_result(activity_id: str, api_key: str, timeout_seconds: int = 600):
    url = f"https://api.fortyguard.com/v1/status/{activity_id}"
    deadline = time.monotonic() + timeout_seconds
    delay = 3

    while time.monotonic() < deadline:
        response = requests.get(url, headers={"api-key": api_key}, timeout=30)
        if response.status_code == 404:  # transient just after submission
            time.sleep(delay)
            continue
        response.raise_for_status()
        data = response.json()["data"]
        status = str(data.get("status", "")).lower()

        if status in {"completed", "succeeded"}:
            return data
        if status in {"failed", "error"}:
            raise RuntimeError(f"FortyGuard activity {activity_id} ended as {status}")

        time.sleep(delay)
        delay = min(delay * 1.25, 10)

    raise TimeoutError(f"FortyGuard activity {activity_id} did not complete in time")
```

Use durable jobs/workers, not a browser request or a single web-server request, for polling. This avoids tying the operator UI to long-running tasks.

## Input validation checklist

Validate before submitting:

- Latitude is `[-90, 90]`; longitude is `[-180, 180]`.
- Location is inside the United States.
- Polygon is a valid GeoJSON FeatureCollection, geometry is a closed Polygon, and area fits plan limits.
- Dates use `YYYY-MM-DD`; times use 24-hour `HH:MM`.
- Most endpoints accept dates from 2019-01-01 through present; heatmap forecast reaches at most 12 hours ahead.
- Heatmap granularity is one of `60`, `80`, `100`.
- Time-range requests adhere to endpoint-specific filter rules. The general limitations page caps `filter_type: 2` at 23 hours; heatmap additionally documents `filter_type: 4` up to one month.
- Heat Intelligence analysis names are from the supported list.

## Energy Grid API usage strategy

1. **Prototype small:** define 6-12 zones that fit comfortably inside one or a few AOIs. Start at 80 m or 100 m for faster, lower-volume work; test 60 m only if it adds visible value.
2. **Use heatmaps as source of truth:** request `tcm` single-hour maps for actual/historical calibration and the 12-hour forecast horizon.
3. **Aggregate locally:** calculate mean/max/stdev temperature for each zone from returned GeoJSON; retain tile count and request provenance.
4. **Avoid duplicate charges:** cache by polygon hash, date/time, filter, granularity, analytics, threshold, and direction. Deduplicate active `activity_id`s.
5. **Enrich selectively:** call environmental parameters only for high-risk zones or calibration experiments. Do not make Premium imagery/report endpoints prerequisites for the demo.
6. **Monitor credits:** use current-cycle usage before demonstrations; place soft quotas in the worker.
7. **Ship a fallback:** retain a completed, real-source response and use it in a clearly marked demo replay if the API is slow or unavailable.

## Key caveats

- The API's current documented availability is US only. Do not use a non-US city for the live prototype.
- Heatmap forecast is limited to 12 hours. Pitch Energy Grid as an intra-day warning system, not a day-ahead market forecast.
- Heatmap API granularity is 60/80/100 m. Do not present response output as 2 m resolution.
- The submission response is asynchronous even if it returns HTTP success. It is not the final heatmap/result.
- Failed tasks are free, but successful tasks consume credits. Avoid retry loops that duplicate a valid submission.
- Status pages can return a transient 404 immediately after submission; retry boundedly.
- Raw segmentation images may not include a data-URI prefix; add it only for rendering.
- Never write an API key or temporary Heat Intelligence signed URL to application logs.

## Source list

- [Introduction](https://docs-api.fortyguard.com/)
- [Quickstart](https://docs-api.fortyguard.com/docs/quickstart)
- [Authentication](https://docs-api.fortyguard.com/docs/authentication)
- [Create Heatmap](https://docs-api.fortyguard.com/docs/create-heatmap)
- [Environmental Parameters](https://docs-api.fortyguard.com/docs/environmental-parameters)
- [Satellite View Segmentation](https://docs-api.fortyguard.com/docs/satellite-view-segmentation)
- [Street View Segmentation](https://docs-api.fortyguard.com/docs/street-view-segmentation)
- [Heat Intelligence](https://docs-api.fortyguard.com/docs/heat-intelligence)
- [Check Status](https://docs-api.fortyguard.com/docs/check-status)
- [Known Limitations](https://docs-api.fortyguard.com/docs/limitations)
- [Release Notes](https://docs-api.fortyguard.com/docs/release-notes)
