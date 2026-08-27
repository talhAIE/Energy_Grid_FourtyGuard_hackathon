# Feature Dataset Contract

## Purpose

Phase 7 produces a reproducible city-level CSV for the baseline demand model. Each row begins with one
persisted EIA demand observation and aligns zone-temperature observations at the **same UTC timestamp**.
No values are interpolated or forward-filled.

## Build command

```powershell
python -m app.scripts.build_feature_dataset --start 2025-08-01T00:00:00Z --end 2025-08-08T00:00:00Z
```

The script writes a versioned CSV and matching `.quality.json` report to `FEATURE_DATASET_DIR` (default:
`app/data/generated/features/`). Generated artifacts are intentionally ignored by Git.

## Row schema

| Field | Type | Description |
| --- | --- | --- |
| `period_utc` | ISO-8601 UTC | Source time shared by EIA target and matched temperatures |
| `period_local` | ISO-8601 local | Same instant in `DEMO_TIMEZONE` for calendar features |
| `target_demand_mw` | decimal | EIA city/grid-area demand target in MW |
| `target_is_actual` | boolean | EIA actual (`true`) versus forecast (`false`) marker |
| `demand_quality_flag` | string/null | Source quality marker when supplied by EIA |
| `city_temperature_c` | decimal/null | Allocation-weighted mean of available zone temperatures |
| `cooling_degree_hours` | decimal/null | `max(0, city_temperature_c - COOLING_BASE_TEMPERATURE_C)` |
| `temperature_coverage_weight` | decimal | Active-zone allocation weight represented by available temperatures |
| `available_zone_count` | integer | Number of active zones with usable temperature values |
| `expected_zone_count` | integer | Number of active zones expected for the city |
| `temperature_source_kind` | enum | `actual`, `forecast`, `mixed`, or `missing` |
| `feature_quality_status` | enum | `complete`, `partial_temperature`, or `missing_temperature` |
| `local_hour` | integer | Local hour `0-23` |
| `local_day_of_week` | integer | Monday `0` through Sunday `6` |
| `is_weekend` | boolean | Saturday/Sunday marker in local time |
| `local_month` | integer | Local month `1-12` |
| `is_us_federal_holiday` | boolean | Built-in observed U.S. federal holiday marker |

## Quality policy

- `complete`: every active zone has a usable same-timestamp observation.
- `partial_temperature`: one or more active zones are missing or unavailable. The available-weight mean is
  retained, and coverage makes the partial input visible.
- `missing_temperature`: no active-zone temperature is available; temperature and CDH remain null.

Later modeling must explicitly select eligible quality states. It must not treat null temperature/CDH as zero
or silently interpolate absent observations.

## Reproducibility

Dataset version is a SHA-256 fingerprint of schema version, city, requested UTC range, cooling baseline, and
feature rows. Rebuilding the same source inputs creates the same versioned artifact name. The quality report
contains row and quality counts, demand-source mix, source-temperature mix, configured time range, and
cooling baseline.
