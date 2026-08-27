# Energy Grid Heat-Demand Forecaster

## Project in one sentence

**Energy Grid** is a human-supervised AI decision-support system that converts FortyGuard's hyperlocal heatmap data into zone-level, 12-hour electricity-demand risk forecasts, giving a utility time to prepare before heat-driven air-conditioning demand strains the grid.

> Demo promise: “Zone 4 is likely to create a demand spike within three hours. Here is the evidence, estimated impact, recommended preparation, and the operator approval needed before action.”

## The problem

Heat waves create sharp electricity-demand peaks because air-conditioning use rises at roughly the same time. A city-wide weather forecast is not enough for a grid operator: exposed commercial districts, low-tree-cover neighbourhoods, and dense built areas can heat differently. If the operator notices only after demand rises, the best preparation window is already gone.

The project addresses four gaps:

- **Spatial gap:** city-wide temperatures do not reveal which operational zone is heating first.
- **Timing gap:** reactive monitoring cannot provide enough lead time to stage capacity or demand-response actions.
- **Decision gap:** raw temperature maps do not tell an operator what to do next.
- **Trust gap:** an AI recommendation needs evidence, data-freshness checks, safety rules, and a human approval record.

## Users and outcome

| User | Need | What Energy Grid provides |
| --- | --- | --- |
| Grid operator | Prepare before a local heat-driven peak | Zone risk, time-to-risk, estimated demand uplift, recommended action |
| Utility planner | Understand recurring heat exposure | Historical risk trends and calibration accuracy |
| City resilience team | Reduce blackout and heat-risk exposure | Clear heat-risk evidence by operational zone |
| Demand-response coordinator | Decide where to target programmes | Ranked zones and a documented approval workflow |

**Outcome:** not an autonomous grid-control product. It is an early-warning and recommendation layer that helps a qualified operator prepare capacity, target voluntary demand response, inspect network constraints, or notify stakeholders. It never sends a control command to a grid.

## Why FortyGuard is central

FortyGuard provides the data layer the model cannot recreate itself: high-resolution, polygon-based heatmaps, including forecast heatmaps up to 12 hours ahead. Its documented heatmap result is GeoJSON plus statistics, making it suitable for aggregating temperatures into utility zones. FortyGuard also positions its technology for energy-demand forecasting and energy resilience. [Heatmap API](https://docs-api.fortyguard.com/docs/create-heatmap) · [API energy use case](https://docs-api.fortyguard.com/) · [FortyGuard technology](https://www.fortyguard.com/our-technology)

Important scope decision: FortyGuard marketing references meter-/2 m-level intelligence, but the documented heatmap API accepts **60 m, 80 m, or 100 m** granularity. This hackathon prototype will truthfully present the API-level resolution it requests, not claim 2 m output.

## Core user flow

1. An operator selects a US demo city and its utility/operational zones.
2. The scheduler creates a FortyGuard heatmap task for each zone (or one larger AOI, then spatially joins tiles to zones) for the present and forecast hours.
3. When tasks complete, the service validates freshness and stores normalized zone-temperature observations.
4. The forecasting service converts temperature into cooling demand features, forecasts each zone's incremental demand, and scores risk from 0 to 100.
5. The agent composes a recommendation only when guardrails pass.
6. The dashboard explains the signal, shows forecast and evidence, and asks a human operator to approve, reject, or defer it.
7. The system records the model version, inputs, recommendation, operator decision, and later outcome.

## How the forecast works

### 1. Temperature signal

For each zone `z` and forecast hour `t`, derive a representative temperature from FortyGuard heatmap tiles:

`T[z,t] = mean(tile temperatures spatially inside zone z)`

Keep max, standard deviation, and tile count as supporting evidence. Prefer `analytic_type: "tcm"`, whose values are temperature in Celsius. Use a single-hour heatmap (`filter_type: 1`) per forecast hour; batch only where the API's supported time-window behavior is tested.

### 2. Cooling-degree feature

Use Cooling Degree Hours (CDH), the hourly analogue of Cooling Degree Days, as the transparent baseline:

`CDH[z,t] = max(0, T[z,t] - T_base)`

Start with `T_base = 18°C` (configurable per city). The baseline is interpretable and can be calibrated using historical demand. It is a model feature, not a claim that all demand is caused by temperature.

### 3. Demand model

For the hackathon, use a two-layer approach:

- **Baseline:** regularised regression or gradient-boosted trees predicting hourly demand from hour of day, day of week, month/holiday flag, lagged demand, and CDH.
- **Zone allocation:** distribute city demand across zones using a transparent exposure weight: heat anomaly, historic peak share, and optionally public building/load proxies.

Example model:

`forecast_load[z,t] = baseline_load[z,t] + beta[z] * CDH[z,t] + gamma * heat_anomaly[z,t]`

Where zone-specific `beta[z]` is learned only when sufficient historical data exists. Where it does not, label the output **proxy estimate** and use a calibrated city-level model plus zone exposure weights.

### 4. Risk score

The 0-100 score should be explainable and thresholded, not an opaque label:

`risk = 100 * sigmoid(0.45 * demand_uplift_pct + 0.30 * heat_anomaly + 0.15 * ramp_rate + 0.10 * uncertainty_penalty)`

Inputs:

- **Demand uplift:** predicted increase over the zone's normal load for that hour.
- **Heat anomaly:** heat above the zone's seasonal/hourly baseline.
- **Ramp rate:** how fast temperature and predicted demand are rising.
- **Uncertainty:** missing, stale, sparse, or poorly calibrated inputs increase caution and reduce automation.

Suggested labels: `0-39 low`, `40-64 watch`, `65-79 high`, `80-100 critical`.

## The agent: observe -> evaluate -> plan -> validate -> ask -> record

The project meets the Agentic AI track because it runs a bounded decision loop; it is not merely a dashboard.

| Stage | Behaviour | Guardrail |
| --- | --- | --- |
| Observe | Fetch and normalize completed heatmap results | Reject stale, failed, invalid, or incomplete data |
| Evaluate | Run demand forecast and uncertainty checks | Use versioned model and features |
| Plan | Draft a zone-specific recommendation | Only use an approved action catalogue |
| Validate | Apply policy thresholds | No advice if confidence/data quality is below threshold |
| Ask | Show evidence to a human operator | Explicit approve/reject/defer; no grid actuation |
| Record | Persist inputs, output, decision, and outcome | Tamper-evident audit ID; no API secrets in logs |

Example action catalogue:

- **Watch:** monitor and schedule a re-check in 30 minutes.
- **High:** verify available reserve capacity; prepare an optional demand-response notification.
- **Critical:** escalate to the duty operator; review reserve and feeder constraints; prepare approved demand-response and public-safety communications.

The app must never claim it has dispatched generation, shed load, changed a switch, or contacted customers unless a separate, authorized integration is built later.

## System architecture

```text
FortyGuard Heatmap API        Public grid-demand data
          |                            |
          v                            v
  async job/poll worker --> normalized time-series store
                                      |
                                      v
                   CDH features + demand forecast + uncertainty
                                      |
                                      v
                         risk engine + policy/guardrail engine
                                      |
                    +-----------------+------------------+
                    v                                    v
              operator dashboard                    immutable audit log
                    |
                    v
         approve / reject / defer recommendation
```

## Recommended technology stack

| Layer | Recommended choice | Why it is the best hackathon trade-off |
| --- | --- | --- |
| Web app | **Next.js + TypeScript** | Fast dashboard delivery, route handlers, strong ecosystem |
| Map and charts | **MapLibre GL JS + deck.gl + Recharts** | Open map rendering, GeoJSON support, performant heat tiles |
| API/service | **Python FastAPI** | Excellent geospatial, modelling, and async-job support |
| Forecasting | **pandas, scikit-learn, statsmodels** | Transparent, credible baseline; no need to train a large model |
| Geospatial | **GeoPandas, Shapely, PostGIS** | Zone/GeoJSON spatial joins and repeatable analysis |
| Database | **PostgreSQL + TimescaleDB/PostGIS** | Time series, spatial querying, audit data in one store |
| Background jobs | **Celery + Redis** (or a simple managed queue) | Isolates asynchronous FortyGuard submit/poll jobs from the UI |
| Deployment | **Vercel (web) + Render/Railway/Fly.io (API/worker)** | Low setup time and reliable public demo |
| Observability | Structured logs + Sentry | Easy error diagnosis without leaking secrets |

If the team needs the smallest viable build, use one Next.js app, a Python worker, Supabase Postgres, and a scheduled job. Do not add an LLM dependency to the risk calculation; use an LLM only to turn already-computed evidence into a readable recommendation, and display the structured evidence alongside it.

## Data plan

### FortyGuard data

- **Primary:** `POST /v1/heatmap`, `analytic_type: "tcm"`, 60/80/100 m granularity, historical/realtime and up-to-12-hour forecast window.
- **Optional enrichment:** `POST /v1/env_params` for apparent temperature, humidity, wet-bulb temperature, AQI, and solar irradiance when plan access and integration time permit.
- **Optional explainability/demo:** satellite/street segmentation can support a later “why this zone runs hotter” insight, but they are Premium-only and are not required for the core forecast.

### Public demand data

Use a location with reliable open historical load data, preferably a US ISO/RTO or utility data portal. Select one city/region before coding and document the data resolution, time zone, missing-data treatment, and licence. Do not present a city-level load series as measured zone-level ground truth; zone output is an allocation/proxy until utility feeder data is available.

### Demo city selection criteria

- Must be inside current FortyGuard API US coverage.
- Has accessible hourly or sub-hourly historical electricity-demand data.
- Has a clearly explainable hot-weather period in the available history.
- Can be represented by 6-12 manageable operational zones inside a heatmap AOI limit.

## Product requirements for the demo

### Required

- Map with 6-12 named zones colored by risk.
- Zone detail panel: temperature forecast, CDH, predicted demand uplift, confidence/data quality, risk reason.
- Timeline of the next 12 hours.
- Recommendation card with approved action options and operator approval controls.
- Activity/task health: FortyGuard request ID, last successful data time, and stale-data warning.
- Audit log for every recommendation and decision.
- Demo mode with cached real API results so the presentation cannot fail because of a long-running job.

### Nice to have

- Historical replay of a heat event.
- What-if baseline slider (e.g., different cooling threshold).
- Environmental-parameter enrichment.
- Satellite/streetview explanation layer for heat-exposure context.

### Explicitly out of scope

- Direct grid or SCADA control.
- Claiming precise feeder-level demand without utility feeder data.
- Predictions beyond the documented 12-hour heatmap forecast window.
- Real customer contact/alerts.

## API integration design

1. Keep `FORTYGUARD_API_KEY` only on the server in `.env`; never call FortyGuard directly from the browser.
2. Submit a heatmap job and persist its `activity_id`, zone/AOI, requested timestamp, and request hash.
3. Poll `GET /v1/status/{activity_id}` with bounded retries and exponential backoff. Treat a short-lived initial `404` as retryable; stop on case-insensitive `Completed`, `Succeeded`, `Failed`, or `Error`.
4. On completion, validate GeoJSON, transform tile values to zone aggregates, and store raw-response provenance safely.
5. Cache results by AOI, time, analytic type, and granularity to prevent duplicate credit consumption.
6. Query usage before the demo and show API health without exposing the key.

For full request, limits, and response details, see [apifourtygaurd.md](apifourtygaurd.md).

## Build plan

| Day | Deliverable |
| --- | --- |
| 1 | Pick demo city/data source; define zones; store secret safely; make first successful heatmap request |
| 2 | Async worker, status polling, raw-result cache, API error states |
| 3 | GeoJSON-to-zone aggregation and a map displaying real temperatures |
| 4 | Historical demand data cleaning and CDH baseline model |
| 5 | Zone risk score, uncertainty flags, back-test chart |
| 6 | Dashboard: map, zone detail, 12-hour timeline |
| 7 | Agent recommendation, rules, approvals, audit records |
| 8 | Historical replay and cached demo scenario |
| 9 | Polish, usability checks, pitch, and failure-mode rehearsal |

## How success will be measured

### Technical

- A completed FortyGuard heatmap run creates usable zone inputs.
- The app shows a new 12-hour risk timeline in the defined forecast window.
- Back-test MAE/MAPE is reported for city-level load; zone values clearly show their proxy/measurement status.
- Every recommendation has a traceable data timestamp, model version, explanation, and human decision.

### Demo and judging

- In under 90 seconds, a judge can see a zone move from watch to high/critical, understand why, and approve a safe recommendation.
- The map demonstrates why spatially granular temperature changes the decision compared with one city-wide forecast.
- The pitch is explicit about limitations and safety: the AI advises; humans decide.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| API jobs take minutes | Poll asynchronously; cache a completed real run for the demo |
| Initial status request returns 404 | Retry boundedly; do not label as failure immediately |
| API coverage limitation | Choose a US demo city early |
| No zone-level demand data | State that zones use modelled allocation/proxy; report city-level validation separately |
| Forecast is only 12 hours | Position product as intra-day operational warning, not day-ahead market forecasting |
| Model overconfidence | Display uncertainty and block recommendations below confidence threshold |
| Live presentation/API failure | Ship a replay/cached scenario and show source timestamp |

## Pitch narrative

“Heat does not hit a city evenly, but grid operations often receive broad forecasts. Energy Grid uses FortyGuard’s spatial temperature intelligence to show which operational zone is likely to drive the next cooling-demand spike. Our transparent model turns heat into an estimated demand uplift; our supervised agent turns that estimate into a safe, auditable recommendation. The operator stays in control. Instead of discovering the risk as the grid strains, they get a head start.”

## References

- [FortyGuard API introduction and energy use case](https://docs-api.fortyguard.com/)
- [Create Heatmap](https://docs-api.fortyguard.com/docs/create-heatmap)
- [Environmental Parameters](https://docs-api.fortyguard.com/docs/environmental-parameters)
- [Known API limitations](https://docs-api.fortyguard.com/docs/limitations)
- [FortyGuard technology page](https://www.fortyguard.com/our-technology)
