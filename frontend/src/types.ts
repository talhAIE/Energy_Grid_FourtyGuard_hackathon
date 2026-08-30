export interface ApiEnvelope<T> {
  data: T;
  data_mode: "live" | "replay";
}

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
  }
}

export interface Health {
  status: string;
  service: string;
  environment: string;
  timestamp: string;
  replay_mode: boolean;
  dependencies: Record<string, string>;
}
export interface Zone {
  id: string;
  city_id: string;
  name: string;
  code: string;
  geometry: GeoJSONGeometry;
  active: boolean;
  allocation_weight: number;
}
export interface GeoJSONGeometry {
  type: "Polygon" | "MultiPolygon";
  coordinates: unknown;
}
export interface ZoneForecast {
  id: string;
  zone_id: string;
  forecast_for: string;
  generated_at: string;
  model_version: string;
  city_forecast_mw: number;
  allocation_weight: number;
  temperature_c: number;
  city_temperature_c?: number;
  heat_anomaly_c?: number;
  baseline_mw?: number;
  predicted_mw: number;
  uplift_pct?: number;
  uncertainty_penalty?: number;
  risk_score: number;
  risk_level: "low" | "watch" | "high" | "critical";
  confidence: "low" | "medium" | "high";
  data_freshness_status: "fresh" | "stale";
}
export interface ForecastSet {
  forecast_for: string;
  generated_at: string;
  model_version: string;
  city_forecast_mw: number;
  forecasts: ZoneForecast[];
}
export interface Recommendation {
  id: string;
  zone_id: string;
  forecast_for: string;
  risk_score: number;
  risk_level: "watch" | "high" | "critical";
  confidence: "medium" | "high";
  status:
    "pending" | "approved" | "rejected" | "deferred" | "expired" | "superseded";
  action: {
    code: string;
    label: string;
    safety_boundary: string;
    urgency: "monitor" | "prepare" | "escalate";
    response_window: string;
    steps: string[];
  };
  expires_at: string;
}
export interface DemandObservation {
  id: string;
  period_utc: string;
  source: string;
  source_area_code: string;
  demand_mw: number;
  is_actual: boolean;
}
export interface ZoneTemperature {
  id: string;
  zone_id: string;
  observed_for: string;
  mean_c: number | null;
  tile_count: number;
  is_forecast: boolean;
  data_status: string;
  source_retrieved_at: string;
}
export interface OperationalGridPlan {
  active_zone_count: number;
  deactivated_zone_count: number;
  columns: number;
  rows: number;
}
export interface AuditEvent {
  id: string;
  event_type: string;
  entity_type: string;
  entity_id: string;
  payload: Record<string, unknown>;
  created_at: string;
}
export interface ActiveModel {
  version: string;
  algorithm: string;
  mae_mw: number;
  quality_policy: string;
}
export interface LiveJob {
  job_id: string;
  status: string;
  provider_status: string | null;
  error_code: string | null;
  poll_attempts: number;
}
export interface LiveZoneSample {
  zone_id: string;
  zone_code: string;
  zone_name: string;
  job: { job_id: string; status: string };
}
export interface LiveSetup {
  forecast_for: string;
  model_version: string;
  model_quality_policy: string;
  model_reused: boolean;
  samples: LiveZoneSample[];
}
