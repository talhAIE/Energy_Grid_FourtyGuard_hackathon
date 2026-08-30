import {
  ActiveModel,
  ApiEnvelope,
  ApiError,
  AuditEvent,
  DemandObservation,
  ForecastSet,
  Health,
  LiveJob,
  LiveSetup,
  OperationalGridPlan,
  Recommendation,
  Zone,
  ZoneForecast,
  ZoneTemperature,
} from "./types";

const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000/api/v1"
).replace(/\/$/, "");

// The API serializes database decimals as strings. Convert the live forecast
// signals at the boundary so every dashboard calculation uses real numbers.
const asNumber = (value: unknown): number => Number(value ?? 0);
const normalizeForecast = (forecast: ZoneForecast): ZoneForecast => ({
  ...forecast,
  city_forecast_mw: asNumber(forecast.city_forecast_mw),
  allocation_weight: asNumber(forecast.allocation_weight),
  temperature_c: asNumber(forecast.temperature_c),
  city_temperature_c: asNumber(forecast.city_temperature_c),
  heat_anomaly_c: asNumber(forecast.heat_anomaly_c),
  baseline_mw: asNumber(forecast.baseline_mw),
  predicted_mw: asNumber(forecast.predicted_mw),
  uplift_pct: asNumber(forecast.uplift_pct),
  uncertainty_penalty: asNumber(forecast.uncertainty_penalty),
  risk_score: asNumber(forecast.risk_score),
});

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = payload?.detail;
    throw new ApiError(
      detail?.message ?? `API request failed (${response.status}).`,
      response.status,
    );
  }
  return payload as T;
}

async function optional<T>(path: string): Promise<T | null> {
  try {
    return await request<T>(path);
  } catch (error) {
    if (error instanceof ApiError && [404, 503].includes(error.status))
      return null;
    throw error;
  }
}

export const fetchHealth = () =>
  request<ApiEnvelope<Health>>("/health").then(
    (result) => result as unknown as Health,
  );
export const fetchZones = () =>
  request<ApiEnvelope<Zone[]>>("/zones").then((result) => result.data);
export const activateOperationalGrid = (columns = 4, rows = 2) =>
  request<ApiEnvelope<OperationalGridPlan>>("/zones/operational-grid", {
    method: "POST",
    body: JSON.stringify({ columns, rows }),
  }).then((result) => result.data);
export const fetchForecasts = () =>
  optional<ApiEnvelope<ForecastSet>>("/forecasts/latest").then((result) =>
    result?.data
      ? {
          ...result.data,
          city_forecast_mw: asNumber(result.data.city_forecast_mw),
          forecasts: result.data.forecasts.map(normalizeForecast),
        }
      : null,
  );
export const fetchRecommendations = () =>
  request<ApiEnvelope<Recommendation[]>>(
    "/recommendations?include_inactive=true",
  ).then((result) => result.data);
export const fetchAuditEvents = () =>
  request<ApiEnvelope<AuditEvent[]>>("/audit-events?limit=100").then(
    (result) => result.data,
  );
export const fetchActiveModel = () =>
  optional<ApiEnvelope<ActiveModel>>("/forecast/models/active").then(
    (result) => result?.data ?? null,
  );
export const fetchDemand = (start: Date, end: Date) =>
  request<ApiEnvelope<DemandObservation[]>>(
    `/data/demand?start=${encodeURIComponent(start.toISOString())}&end=${encodeURIComponent(end.toISOString())}&limit=168`,
  ).then((result) => result.data);
export const fetchTemperatures = (start: Date, end: Date) =>
  request<ApiEnvelope<ZoneTemperature[]>>(
    `/temperatures?start=${encodeURIComponent(start.toISOString())}&end=${encodeURIComponent(end.toISOString())}&limit=100`,
  ).then((result) => result.data);
export const fetchZoneTimeline = (zoneId: string) =>
  optional<ApiEnvelope<ZoneForecast[]>>(
    `/forecasts/zones/${zoneId}?limit=24`,
  ).then((result) => (result?.data ?? []).map(normalizeForecast));
export const startLiveSetup = () =>
  request<ApiEnvelope<LiveSetup>>("/live/setup", { method: "POST" }).then(
    (result) => result.data,
  );
export const pollLiveJob = (jobId: string) =>
  request<ApiEnvelope<LiveJob>>(`/jobs/${jobId}/poll`, { method: "POST" }).then(
    (result) => result.data,
  );
export const runForecast = (forecastFor: string) =>
  request("/forecast/run", {
    method: "POST",
    body: JSON.stringify({ forecast_for: forecastFor }),
  });

export const recordDecision = (
  recommendationId: string,
  decision: "approved" | "rejected",
  operator_name: string,
  note: string,
) =>
  request(`/recommendations/${recommendationId}/decision`, {
    method: "POST",
    body: JSON.stringify({ decision, operator_name, note: note || null }),
  });
