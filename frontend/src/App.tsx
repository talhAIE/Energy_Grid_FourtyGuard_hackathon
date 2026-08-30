import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

import {
  activateOperationalGrid,
  fetchActiveModel,
  fetchAuditEvents,
  fetchDemand,
  fetchForecasts,
  fetchHealth,
  fetchRecommendations,
  fetchTemperatures,
  fetchZoneTimeline,
  fetchZones,
  pollLiveJob,
  recordDecision,
  runForecast,
  startLiveSetup,
} from "./api";
import {
  ActiveModel,
  ApiError,
  AuditEvent,
  DemandObservation,
  Health,
  LiveSetup,
  LiveZoneSample,
  Recommendation,
  Zone,
  ZoneForecast,
  ZoneTemperature,
} from "./types";

type Tab = "overview" | "zones" | "demand" | "recommendations" | "audit";
type LiveRun = {
  forecastFor: string;
  samples: LiveZoneSample[];
  status: "collecting" | "forecasting" | "completed" | "failed";
  error?: string;
};
type Position = [number, number];
const TABS: Array<{ id: Tab; label: string; icon: string }> = [
  { id: "overview", label: "Overview", icon: "◈" },
  { id: "zones", label: "Zone map", icon: "⌖" },
  { id: "demand", label: "Demand", icon: "⌁" },
  { id: "recommendations", label: "Review queue", icon: "✓" },
  { id: "audit", label: "Audit log", icon: "≡" },
];
const RISK_CLASSES: Record<string, string> = {
  low: "border-emerald-300/20 bg-emerald-400/15 text-emerald-200",
  watch: "border-amber-300/20 bg-amber-400/15 text-amber-200",
  high: "border-orange-300/20 bg-orange-400/15 text-orange-200",
  critical: "border-red-300/20 bg-red-400/15 text-red-200",
};
const MAP_COLORS: Record<string, string> = {
  low: "#34d399",
  watch: "#fbbf24",
  high: "#fb923c",
  critical: "#fb7185",
};
const number = (value: number | undefined, digits = 0) =>
  value === undefined
    ? "—"
    : new Intl.NumberFormat("en-US", { maximumFractionDigits: digits }).format(
        value,
      );
const time = (value: string | undefined) =>
  value
    ? new Intl.DateTimeFormat("en-US", {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(new Date(value))
    : "—";
const errorText = (error: unknown) =>
  error instanceof ApiError
    ? error.message
    : "Could not reach the Energy Grid API.";
const isCalibrated = (model: ActiveModel | null) =>
  model?.quality_policy === "complete_temperature_only";

export default function App() {
  const [tab, setTab] = useState<Tab>("overview");
  const [health, setHealth] = useState<Health | null>(null);
  const [zones, setZones] = useState<Zone[]>([]);
  const [forecasts, setForecasts] = useState<ZoneForecast[]>([]);
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [demand, setDemand] = useState<DemandObservation[]>([]);
  const [temperatures, setTemperatures] = useState<ZoneTemperature[]>([]);
  const [model, setModel] = useState<ActiveModel | null>(null);
  const [selectedZoneId, setSelectedZoneId] = useState<string | null>(null);
  const [timeline, setTimeline] = useState<ZoneForecast[]>([]);
  const [liveRun, setLiveRun] = useState<LiveRun | null>(null);
  const [selectedRecommendation, setSelectedRecommendation] =
    useState<Recommendation | null>(null);
  const [operatorName, setOperatorName] = useState("Grid operator");
  const [decisionNote, setDecisionNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const forecastByZone = useMemo(
    () => new Map(forecasts.map((forecast) => [forecast.zone_id, forecast])),
    [forecasts],
  );
  const selectedZone =
    zones.find((zone) => zone.id === selectedZoneId) ?? zones[0] ?? null;
  const pendingCount = recommendations.filter(
    (item) => item.status === "pending",
  ).length;
  const highRiskCount = forecasts.filter((item) =>
    ["high", "critical"].includes(item.risk_level),
  ).length;
  const refresh = async () => {
    setBusy(true);
    setError(null);
    try {
      const now = new Date();
      const weekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
      const future = new Date(now.getTime() + 13 * 60 * 60 * 1000);
      const [
        nextHealth,
        nextZones,
        forecastResult,
        recs,
        audits,
        activeModel,
        demandRows,
        temperatureRows,
      ] = await Promise.all([
        fetchHealth(),
        fetchZones(),
        fetchForecasts(),
        fetchRecommendations(),
        fetchAuditEvents(),
        fetchActiveModel(),
        fetchDemand(weekAgo, now),
        fetchTemperatures(weekAgo, future),
      ]);
      setHealth(nextHealth);
      setZones(nextZones);
      const activeZoneIds = new Set(nextZones.map((zone) => zone.id));
      setForecasts(
        (forecastResult?.forecasts ?? []).filter((forecast) =>
          activeZoneIds.has(forecast.zone_id),
        ),
      );
      setRecommendations(recs);
      setAuditEvents(audits);
      setModel(activeModel);
      setDemand(demandRows);
      setTemperatures(temperatureRows);
      setSelectedZoneId((current) => current ?? nextZones[0]?.id ?? null);
    } catch (nextError) {
      setError(errorText(nextError));
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => {
    void refresh();
  }, []);
  useEffect(() => {
    if (selectedZoneId)
      void fetchZoneTimeline(selectedZoneId)
        .then(setTimeline)
        .catch(() => setTimeline([]));
  }, [selectedZoneId]);
  useEffect(() => {
    if (!liveRun || liveRun.status !== "collecting") return;
    const timer = window.setTimeout(() => {
      void (async () => {
        try {
          const jobs = await Promise.all(
            liveRun.samples.map((sample) => pollLiveJob(sample.job.job_id)),
          );
          const failed = jobs.find((job) =>
            ["failed", "submission_failed", "timed_out"].includes(job.status),
          );
          if (failed) {
            setLiveRun((current) =>
              current
                ? {
                    ...current,
                    status: "failed",
                    error: failed.error_code ?? "Provider job failed",
                  }
                : current,
            );
            setError(
              `Live temperature collection stopped: ${failed.error_code ?? "provider job failed"}.`,
            );
            return;
          }
          if (jobs.every((job) => job.status === "completed")) {
            setLiveRun((current) =>
              current ? { ...current, status: "forecasting" } : current,
            );
            await runForecast(liveRun.forecastFor);
            setLiveRun((current) =>
              current ? { ...current, status: "completed" } : current,
            );
            await refresh();
            setMessage(
              "All live zone samples and the complete proxy forecast are ready.",
            );
          }
        } catch (nextError) {
          setError(errorText(nextError));
        }
      })();
    }, 8000);
    return () => window.clearTimeout(timer);
  }, [liveRun]);
  const runLiveForecast = async () => {
    if (!health || health.replay_mode) {
      setError("Live collection requires REPLAY_MODE=false.");
      return;
    }
    setBusy(true);
    try {
      const started: LiveSetup = await startLiveSetup();
      setLiveRun({
        forecastFor: started.forecast_for,
        samples: started.samples,
        status: "collecting",
      });
      setMessage(
        `Submitted ${started.samples.length} bounded live zone samples.`,
      );
    } catch (nextError) {
      setError(errorText(nextError));
    } finally {
      setBusy(false);
    }
  };
  const activateThirtyZonePlan = async () => {
    const confirmed = window.confirm(
      "Activate the approved 30-zone planning grid? The previous plan will be retained as inactive history. Run a live forecast afterward to populate the new cells.",
    );
    if (!confirmed) return;
    setBusy(true);
    setError(null);
    try {
      const plan = await activateOperationalGrid(6, 5);
      await refresh();
      setTab("zones");
      setMessage(
        `Activated ${plan.active_zone_count} approved planning cells. Run the complete live forecast to collect fresh zone inputs.`,
      );
    } catch (nextError) {
      setError(errorText(nextError));
    } finally {
      setBusy(false);
    }
  };
  const decide = async (
    event: FormEvent<HTMLFormElement>,
    decision: "approved" | "rejected",
  ) => {
    event.preventDefault();
    if (!selectedRecommendation) return;
    setBusy(true);
    try {
      await recordDecision(
        selectedRecommendation.id,
        decision,
        operatorName,
        decisionNote,
      );
      setSelectedRecommendation(null);
      setDecisionNote("");
      await refresh();
    } catch (nextError) {
      setError(errorText(nextError));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="min-h-screen bg-[#050816] text-slate-100">
      <header className="sticky top-0 z-20 border-b border-white/10 bg-[#070b1b]/90 backdrop-blur-xl">
        <div className="mx-auto flex max-w-[1440px] flex-wrap items-center justify-between gap-4 px-5 py-4 lg:px-8">
          <div className="flex items-center gap-3">
            <div className="grid size-10 place-items-center rounded-xl bg-lime-300 text-lg font-black text-slate-950">
              ↯
            </div>
            <div>
              <p className="text-[10px] font-bold uppercase tracking-[.24em] text-lime-300">
                Energy Grid
              </p>
              <h1 className="text-lg font-bold tracking-tight">
                Heat-demand operations console
              </h1>
            </div>
          </div>
          <div className="flex items-center gap-3 text-sm">
            <span
              className={`hidden rounded-full border px-3 py-1.5 sm:inline ${health?.replay_mode ? "border-amber-300/20 bg-amber-400/10 text-amber-100" : "border-emerald-300/20 bg-emerald-400/10 text-emerald-100"}`}
            >
              {health?.replay_mode ? "Replay mode" : "● Live data connected"}
            </span>
            <span className="hidden text-slate-400 md:inline">
              API{" "}
              <b className="text-slate-200">
                {health?.dependencies.database ?? "checking"}
              </b>
            </span>
            <button
              className="rounded-lg border border-white/15 px-3.5 py-2 font-medium hover:border-lime-300 disabled:opacity-50"
              disabled={busy}
              onClick={() => void refresh()}
            >
              {busy ? "Refreshing…" : "Refresh"}
            </button>
          </div>
        </div>
      </header>
      <div className="mx-auto grid max-w-[1440px] gap-6 px-5 py-6 lg:grid-cols-[15rem_1fr] lg:px-8">
        <aside className="rounded-2xl border border-white/10 bg-white/[.035] p-3 lg:self-start">
          <p className="px-3 pb-2 pt-1 text-[10px] font-bold uppercase tracking-[.16em] text-slate-500">
            Operations
          </p>
          <nav className="grid gap-1">
            {TABS.map((item) => (
              <button
                key={item.id}
                onClick={() => setTab(item.id)}
                className={`flex items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm transition ${tab === item.id ? "bg-lime-300 font-bold text-slate-950" : "text-slate-300 hover:bg-white/5 hover:text-white"}`}
              >
                <span className="w-4 text-center">{item.icon}</span>
                {item.label}
              </button>
            ))}
          </nav>
          <div className="mt-5 grid grid-cols-2 gap-2 border-t border-white/10 pt-4">
            <MiniStat label="Awaiting review" value={String(pendingCount)} />
            <MiniStat label="High risk" value={String(highRiskCount)} />
          </div>
          <div className="mt-4 rounded-xl border border-emerald-300/10 bg-emerald-400/[.06] p-3 text-xs leading-5 text-emerald-100">
            <b>Live sources</b>
            <br />
            EIA/ERCOT · FortyGuard
          </div>
        </aside>
        <main className="min-w-0">
          {error && (
            <Banner tone="error" text={error} onClose={() => setError(null)} />
          )}
          {message && (
            <Banner
              tone="success"
              text={message}
              onClose={() => setMessage(null)}
            />
          )}
          {tab === "overview" && (
            <Overview
              health={health}
              model={model}
              zones={zones}
              forecasts={forecasts}
              temperatures={temperatures}
              liveRun={liveRun}
              onRun={runLiveForecast}
              busy={busy}
              forecastByZone={forecastByZone}
              selectedZoneId={selectedZoneId}
              onSelect={setSelectedZoneId}
            />
          )}
          {tab === "zones" && (
            <Zones
              zones={zones}
              forecastByZone={forecastByZone}
              selectedZone={selectedZone}
              timeline={timeline}
              onSelect={setSelectedZoneId}
              onActivateGrid={activateThirtyZonePlan}
              busy={busy}
            />
          )}
          {tab === "demand" && <Demand demand={demand} />}
          {tab === "recommendations" && (
            <Recommendations
              items={recommendations}
              onReview={setSelectedRecommendation}
              model={model}
              forecasts={forecasts}
            />
          )}
          {tab === "audit" && <Audit events={auditEvents} />}
        </main>
      </div>
      {selectedRecommendation && (
        <div className="fixed inset-0 z-30 grid place-items-center bg-black/70 p-4">
          <form
            onSubmit={(event) => void decide(event, "approved")}
            className="w-full max-w-lg rounded-2xl border border-white/15 bg-slate-950 p-6 shadow-2xl"
          >
            <h2 className="text-xl font-bold">
              {selectedRecommendation.action.label}
            </h2>
            <p className="mt-3 text-sm text-slate-300">
              {selectedRecommendation.action.safety_boundary}
            </p>
            <label className="mt-5 block text-sm">
              Operator name
              <input
                required
                minLength={2}
                value={operatorName}
                onChange={(event) => setOperatorName(event.target.value)}
                className="mt-1 w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2"
              />
            </label>
            <label className="mt-4 block text-sm">
              Decision note
              <textarea
                value={decisionNote}
                onChange={(event) => setDecisionNote(event.target.value)}
                className="mt-1 min-h-24 w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2"
              />
            </label>
            <div className="mt-5 flex justify-end gap-3">
              <button
                type="button"
                onClick={() => setSelectedRecommendation(null)}
                className="rounded-lg border border-white/15 px-4 py-2"
              >
                Cancel
              </button>
              <button
                disabled={busy}
                className="rounded-lg bg-lime-300 px-4 py-2 font-bold text-slate-950"
              >
                Approve
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}

function Overview({
  health,
  model,
  zones,
  forecasts,
  temperatures,
  liveRun,
  onRun,
  busy,
  forecastByZone,
  selectedZoneId,
  onSelect,
}: {
  health: Health | null;
  model: ActiveModel | null;
  zones: Zone[];
  forecasts: ZoneForecast[];
  temperatures: ZoneTemperature[];
  liveRun: LiveRun | null;
  onRun: () => void;
  busy: boolean;
  forecastByZone: Map<string, ZoneForecast>;
  selectedZoneId: string | null;
  onSelect: (id: string) => void;
}) {
  const latest = forecasts[0];
  const heat = temperatures
    .filter((item) => item.data_status === "available")
    .sort((a, b) => b.observed_for.localeCompare(a.observed_for))[0];
  const status =
    liveRun?.status === "collecting"
      ? `Collecting ${liveRun.samples.length} zones`
      : liveRun?.status === "forecasting"
        ? "Forecasting"
        : liveRun?.status === "completed"
          ? "Updated"
          : "Ready";
  return (
    <section className="space-y-6">
      <div className="overflow-hidden rounded-3xl border border-white/10 bg-[radial-gradient(circle_at_80%_0%,rgba(163,230,53,.17),transparent_35%),linear-gradient(135deg,rgba(15,23,42,.95),rgba(9,14,31,.95))] p-6 sm:p-8">
        <div className="flex flex-wrap items-start justify-between gap-5">
          <div>
            <span className="inline-flex rounded-full border border-emerald-300/20 bg-emerald-400/10 px-3 py-1 text-xs font-bold text-emerald-100">
              {health?.replay_mode ? "Replay inputs" : "● Live data active"}
            </span>
            <p className="mt-4 text-sm text-sky-200/80">
              Houston, Texas · real demand + live temperature samples
            </p>
            <h2 className="mt-2 text-3xl font-bold tracking-tight sm:text-4xl">
              Operational heat risk, clearly explained.
            </h2>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-300">
              Live zone temperatures and EIA/ERCOT demand history produce
              transparent proxy forecasts. No dispatch or control action is
              taken.
            </p>
          </div>
          <button
            disabled={
              busy ||
              health?.replay_mode ||
              liveRun?.status === "collecting" ||
              liveRun?.status === "forecasting"
            }
            onClick={onRun}
            className="rounded-xl bg-lime-300 px-4 py-3 text-sm font-bold text-slate-950 shadow-[0_0_30px_rgba(190,242,100,.18)] disabled:opacity-50"
          >
            Run complete live forecast
          </button>
        </div>
        {liveRun && (
          <div className="mt-6 rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
            <b>{status}</b> · forecast target {time(liveRun.forecastFor)} ·{" "}
            {liveRun.error ?? "provider jobs are processed safely"}
          </div>
        )}
      </div>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Metric
          label="Live zone coverage"
          value={`${forecasts.length}/${zones.length}`}
          detail="completed proxy forecasts"
          accent="lime"
        />
        <Metric
          label="City forecast"
          value={latest ? `${number(latest.city_forecast_mw)} MW` : "—"}
          detail={
            latest ? `for ${time(latest.forecast_for)}` : "run a collection"
          }
          accent="sky"
        />
        <Metric
          label="Heat sample"
          value={heat ? `${number(heat.mean_c ?? undefined, 1)}°C` : "—"}
          detail={
            heat
              ? `${number(heat.tile_count)} live tiles`
              : "no completed sample"
          }
          accent="orange"
        />
        <Metric
          label="Model status"
          value={
            model ? (isCalibrated(model) ? "Calibrated" : "Bootstrap") : "—"
          }
          detail={
            model ? `MAE ${number(model.mae_mw)} MW` : "live history required"
          }
          accent={isCalibrated(model) ? "lime" : "violet"}
        />
      </div>
      <div className="grid gap-6 xl:grid-cols-[1.4fr_.8fr]">
        <LiveMap
          zones={zones}
          forecastByZone={forecastByZone}
          selectedZoneId={selectedZoneId}
          onSelect={onSelect}
        />
        <div className="space-y-4">
          <div className="rounded-2xl border border-white/10 bg-white/[.035] p-5">
            <p className="text-xs font-bold uppercase tracking-[.14em] text-slate-500">
              Recommendation gate
            </p>
            <h3 className="mt-2 text-xl font-bold">
              {isCalibrated(model)
                ? "Ready for eligible risks"
                : "Waiting for calibration"}
            </h3>
            <p className="mt-2 text-sm leading-6 text-slate-300">
              Recommendations are intentionally empty: this EIA-history
              bootstrap is not yet a calibrated temperature-demand model.
            </p>
            <Gate ready label="Live EIA/ERCOT demand" />
            <Gate
              ready={forecasts.length === zones.length && zones.length > 0}
              label="All zones sampled live"
            />
            <Gate
              ready={isCalibrated(model)}
              label="Calibrated weather-history model"
            />
            <Gate ready={false} label="Medium/high risk threshold" />
          </div>
          <div className="rounded-2xl border border-sky-300/15 bg-sky-400/[.06] p-5 text-sm leading-6 text-sky-50">
            <b className="text-sky-200">Today’s result</b>
            <br />
            All completed zones are low risk. The queue will activate only when
            both model calibration and a qualifying future risk are present.
          </div>
        </div>
      </div>
    </section>
  );
}
function Zones({
  zones,
  forecastByZone,
  selectedZone,
  timeline,
  onSelect,
  onActivateGrid,
  busy,
}: {
  zones: Zone[];
  forecastByZone: Map<string, ZoneForecast>;
  selectedZone: Zone | null;
  timeline: ZoneForecast[];
  onSelect: (id: string) => void;
  onActivateGrid: () => void;
  busy: boolean;
}) {
  const forecast = selectedZone
    ? forecastByZone.get(selectedZone.id)
    : undefined;
  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm text-sky-200/80">
            Live zone temperature and proxy-demand view
          </p>
          <h2 className="mt-1 text-3xl font-bold">Houston zone map</h2>
          <p className="mt-2 text-sm text-slate-400">
            {zones.length} active planning zones · allocation weights update
            automatically with the active plan.
          </p>
        </div>
        {zones.length < 20 && (
          <button
            onClick={onActivateGrid}
            disabled={busy}
            className="rounded-xl bg-lime-300 px-4 py-3 text-sm font-bold text-slate-950 shadow-[0_0_26px_rgba(190,242,100,.16)] disabled:opacity-50"
          >
            Use approved 30-zone plan
          </button>
        )}
      </div>
      <div className="grid gap-6 xl:grid-cols-[1.15fr_.85fr]">
        <LiveMap
          zones={zones}
          forecastByZone={forecastByZone}
          selectedZoneId={selectedZone?.id ?? null}
          onSelect={onSelect}
          large
        />
        <div className="rounded-2xl border border-white/10 bg-white/[.035] p-5">
          <p className="text-xs font-bold uppercase tracking-[.14em] text-slate-500">
            Selected zone
          </p>
          <h3 className="mt-2 text-2xl font-bold">
            {selectedZone?.name ?? "Select a zone"}
          </h3>
          {selectedZone && (
            <>
              <p className="mt-1 text-sm text-slate-400">
                {selectedZone.code} · allocation{" "}
                {number(selectedZone.allocation_weight * 100, 0)}%
              </p>
              <div className="mt-5 grid grid-cols-2 gap-3">
                <Info
                  label="Temperature"
                  value={`${number(forecast?.temperature_c, 1)}°C`}
                />
                <Info
                  label="Proxy demand"
                  value={`${number(forecast?.predicted_mw)} MW`}
                />
                <Info
                  label="Risk score"
                  value={number(forecast?.risk_score, 1)}
                />
                <Info
                  label="Risk level"
                  value={forecast?.risk_level ?? "unavailable"}
                />
              </div>
              <h4 className="mt-7 text-sm font-bold">Forecast timeline</h4>
              <div className="mt-3 space-y-2">
                {timeline.length ? (
                  timeline.map((item) => (
                    <div
                      key={item.id}
                      className="flex items-center justify-between rounded-lg border border-white/8 bg-black/15 px-3 py-2 text-sm"
                    >
                      <span className="text-slate-400">
                        {time(item.forecast_for)}
                      </span>
                      <span>{number(item.temperature_c, 1)}°C</span>
                      <RiskBadge risk={item.risk_level} />
                    </div>
                  ))
                ) : (
                  <p className="text-sm text-slate-400">No stored timeline.</p>
                )}
              </div>
            </>
          )}
        </div>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        {zones.map((zone) => {
          const item = forecastByZone.get(zone.id);
          return (
            <button
              key={zone.id}
              onClick={() => onSelect(zone.id)}
              className={`rounded-xl border p-4 text-left ${selectedZone?.id === zone.id ? "border-lime-300 bg-lime-300/10" : "border-white/10 bg-white/[.035] hover:border-white/25"}`}
            >
              <div className="flex justify-between gap-4">
                <div>
                  <p className="font-bold">{zone.name}</p>
                  <p className="mt-1 text-xs text-slate-500">{zone.code}</p>
                </div>
                <RiskBadge risk={item?.risk_level} />
              </div>
              <p className="mt-3 text-sm text-slate-300">
                {item
                  ? `${number(item.temperature_c, 1)}°C · ${number(item.predicted_mw)} MW · risk ${number(item.risk_score, 1)}`
                  : "Forecast unavailable"}
              </p>
            </button>
          );
        })}
      </div>
    </section>
  );
}
function Recommendations({
  items,
  onReview,
  model,
  forecasts,
}: {
  items: Recommendation[];
  onReview: (item: Recommendation) => void;
  model: ActiveModel | null;
  forecasts: ZoneForecast[];
}) {
  const highestForecast = forecasts.reduce(
    (current, item) =>
      !current || item.risk_score > current.risk_score ? item : current,
    null as ZoneForecast | null,
  );
  const posture = operationalPosture(highestForecast, model);
  return (
    <section className="space-y-6">
      <div>
        <p className="text-sm text-sky-200/80">
          Human-reviewed decision support only
        </p>
        <h2 className="mt-1 text-3xl font-bold">Review queue</h2>
      </div>
      {items.length ? (
        <div className="space-y-3">
          {items.map((item) => (
            <article
              key={item.id}
              className="rounded-2xl border border-white/10 bg-white/[.035] p-5"
            >
              <div className="flex flex-wrap items-center justify-between gap-3">
                <RiskBadge risk={item.risk_level} />
                <span className="rounded-full bg-sky-400/10 px-2.5 py-1 text-xs font-semibold text-sky-200">
                  {item.action.response_window}
                </span>
              </div>
              <h3 className="mt-3 font-bold">{item.action.label}</h3>
              <p className="mt-2 text-sm text-slate-400">
                {item.action.safety_boundary}
              </p>
              <ol className="mt-4 space-y-2 text-sm text-slate-200">
                {item.action.steps.map((step, index) => (
                  <li key={step} className="flex gap-3">
                    <span className="grid size-5 shrink-0 place-items-center rounded-full bg-slate-800 text-xs text-lime-200">
                      {index + 1}
                    </span>
                    {step}
                  </li>
                ))}
              </ol>
              {item.status === "pending" && (
                <button
                  onClick={() => onReview(item)}
                  className="mt-4 rounded-lg bg-lime-300 px-3 py-2 text-sm font-bold text-slate-950"
                >
                  Review
                </button>
              )}
            </article>
          ))}
        </div>
      ) : (
        <div className="grid gap-5 lg:grid-cols-[1.2fr_.8fr]">
          <div className="rounded-2xl border border-amber-300/15 bg-amber-400/[.06] p-6">
            <p className="text-xs font-bold uppercase tracking-[.14em] text-amber-200">
              Why the queue is empty
            </p>
            <h3 className="mt-2 text-2xl font-bold">
              No recommendation is safe to issue yet.
            </h3>
            <p className="mt-3 text-sm leading-6 text-slate-200">
              The dashboard has real live data and complete zone forecasts, but
              its current demand-history bootstrap cannot responsibly produce
              operational recommendations.
            </p>
            <p className="mt-4 rounded-xl border border-white/10 bg-black/15 p-4 text-sm">
              <b>Current risk:</b>{" "}
              {forecasts.length
                ? "all live zones are low risk."
                : "no completed forecast."}
              <br />
              <b>Missing gate:</b>{" "}
              {isCalibrated(model)
                ? "an eligible future medium/high risk."
                : "a calibrated temperature-demand model."}
            </p>
          </div>
          <div className="rounded-2xl border border-white/10 bg-white/[.035] p-6">
            <p className="text-xs font-bold uppercase tracking-[.14em] text-slate-500">
              Policy checklist
            </p>
            <Gate ready label="Fresh provider temperature" />
            <Gate ready={forecasts.length > 0} label="Future proxy forecast" />
            <Gate ready={isCalibrated(model)} label="Calibrated model" />
            <Gate ready={false} label="Actionable risk score" />
          </div>
        </div>
      )}
      <section className="rounded-2xl border border-sky-300/20 bg-sky-400/[.05] p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs font-bold uppercase tracking-[.14em] text-sky-200">
              Live operational posture
            </p>
            <h3 className="mt-2 text-xl font-bold">{posture.title}</h3>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-300">
              {posture.summary}
            </p>
          </div>
          <span
            className={`rounded-full px-3 py-1.5 text-xs font-bold ${posture.badgeClass}`}
          >
            {posture.badge}
          </span>
        </div>
        <div className="mt-5 grid gap-3 md:grid-cols-3">
          {posture.steps.map((step, index) => (
            <div
              key={step}
              className="rounded-xl border border-white/10 bg-black/15 p-4 text-sm text-slate-200"
            >
              <span className="text-xs font-bold text-sky-200">
                STEP {index + 1}
              </span>
              <p className="mt-2 leading-6">{step}</p>
            </div>
          ))}
        </div>
        <p className="mt-5 text-xs text-slate-400">
          This is a planning checklist, not a dispatch instruction. Formal
          recommendations require every policy gate to pass.
        </p>
      </section>
    </section>
  );
}
function operationalPosture(
  forecast: ZoneForecast | null,
  model: ActiveModel | null,
) {
  if (!forecast) {
    return {
      title: "Awaiting a completed live forecast",
      summary:
        "Collect a fresh FortyGuard zone sample and EIA/ERCOT demand input before using the planning workflow.",
      badge: "Data needed",
      badgeClass: "bg-slate-700/70 text-slate-200",
      steps: [
        "Confirm the live data sources are connected.",
        "Run the complete live forecast.",
        "Review the map once every operational zone has a result.",
      ],
    };
  }
  if (!isCalibrated(model)) {
    return {
      title: "Maintain monitoring; do not issue an operational recommendation",
      summary: `The highest current signal is ${number(forecast.risk_score, 1)}/100 (${forecast.risk_level}). Live inputs are available, but the active bootstrap model has not yet completed temperature-demand calibration.`,
      badge: "Calibration required",
      badgeClass: "bg-amber-400/15 text-amber-100",
      steps: [
        "Monitor the selected high-signal zone on the live map.",
        "Re-run the forecast when the next live temperature sample is available.",
        "Use the demand-history view to check for an unusual load pattern; escalate only through approved procedures.",
      ],
    };
  }
  if (forecast.risk_level === "critical") {
    return {
      title: "Initiate immediate duty-operator review",
      summary: `The highest zone signal is ${number(forecast.risk_score, 1)}/100. Review the evidence and the approved response plan before any operational action.`,
      badge: "Immediate review",
      badgeClass: "bg-rose-400/15 text-rose-100",
      steps: [
        "Escalate the forecast and its evidence to the duty operator.",
        "Review the approved response plan and current operating constraints.",
        "Record an explicit human decision in the review queue.",
      ],
    };
  }
  if (forecast.risk_level === "high") {
    return {
      title: "Prepare an operator-readiness review",
      summary: `The highest zone signal is ${number(forecast.risk_score, 1)}/100. Verify readiness now; do not enact a response without a separate human approval.`,
      badge: "Prepare",
      badgeClass: "bg-orange-400/15 text-orange-100",
      steps: [
        "Notify the duty operator that a high-risk forecast is available.",
        "Verify reserve and approved response-plan readiness.",
        "Prepare voluntary response options for human review.",
      ],
    };
  }
  return {
    title: "Maintain normal monitoring",
    summary: `The highest live zone signal is ${number(forecast.risk_score, 1)}/100 (${forecast.risk_level}). No operational response is indicated; keep the next forecast cycle under observation.`,
    badge: "Monitor",
    badgeClass: "bg-emerald-400/15 text-emerald-100",
    steps: [
      "Keep the live map open during the current forecast window.",
      "Recheck conditions when the next FortyGuard sample arrives.",
      "Review the demand history for unexpected demand movement.",
    ],
  };
}
function Demand({ demand }: { demand: DemandObservation[] }) {
  return (
    <section>
      <p className="text-sm text-sky-200/80">Real EIA/ERCOT hourly records</p>
      <h2 className="mt-1 text-3xl font-bold">Demand history</h2>
      <div className="mt-6 overflow-hidden rounded-2xl border border-white/10 bg-white/[.035]">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-white/10 bg-black/15 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="p-4">Time</th>
              <th className="p-4">Demand</th>
              <th className="p-4">Source</th>
              <th className="p-4">Status</th>
            </tr>
          </thead>
          <tbody>
            {demand.map((item) => (
              <tr key={item.id} className="border-b border-white/5">
                <td className="p-4 text-slate-300">{time(item.period_utc)}</td>
                <td className="p-4 font-semibold">
                  {number(item.demand_mw)} MW
                </td>
                <td className="p-4 text-slate-400">
                  {item.source} / {item.source_area_code}
                </td>
                <td className="p-4 text-emerald-200">
                  {item.is_actual ? "Actual" : "Forecast"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
function Audit({ events }: { events: AuditEvent[] }) {
  return (
    <section>
      <p className="text-sm text-sky-200/80">Read-only, redacted history</p>
      <h2 className="mt-1 text-3xl font-bold">Audit log</h2>
      <div className="mt-6 space-y-3">
        {events.map((event) => (
          <article
            key={event.id}
            className="rounded-xl border border-white/10 bg-white/[.035] p-4"
          >
            <div className="flex justify-between gap-3">
              <p className="font-bold">{event.event_type}</p>
              <p className="text-sm text-slate-500">{time(event.created_at)}</p>
            </div>
            <p className="mt-2 text-xs text-slate-500">
              {event.entity_type} · {event.entity_id}
            </p>
            <pre className="mt-3 overflow-x-auto rounded-lg bg-black/25 p-3 text-xs text-slate-300">
              {JSON.stringify(event.payload, null, 2)}
            </pre>
          </article>
        ))}
      </div>
    </section>
  );
}
function LiveMap({
  zones,
  forecastByZone,
  selectedZoneId,
  onSelect,
  large = false,
}: {
  zones: Zone[];
  forecastByZone: Map<string, ZoneForecast>;
  selectedZoneId: string | null;
  onSelect: (id: string) => void;
  large?: boolean;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const layersRef = useRef<L.FeatureGroup | null>(null);
  const didFitRef = useRef(false);
  const selectedZone =
    zones.find((zone) => zone.id === selectedZoneId) ?? zones[0] ?? null;
  const selectedForecast = selectedZone
    ? forecastByZone.get(selectedZone.id)
    : undefined;
  const liveForecasts = zones
    .map((zone) => ({ zone, forecast: forecastByZone.get(zone.id) }))
    .filter((item): item is { zone: Zone; forecast: ZoneForecast } =>
      Boolean(item.forecast),
    );
  const hottestZone = liveForecasts.reduce(
    (current, item) =>
      !current || item.forecast.temperature_c > current.forecast.temperature_c
        ? item
        : current,
    null as { zone: Zone; forecast: ZoneForecast } | null,
  );
  const largestLoadZone = liveForecasts.reduce(
    (current, item) =>
      !current || item.forecast.predicted_mw > current.forecast.predicted_mw
        ? item
        : current,
    null as { zone: Zone; forecast: ZoneForecast } | null,
  );
  const priorityZones = [...liveForecasts]
    .sort(
      (left, right) =>
        right.forecast.risk_score - left.forecast.risk_score ||
        right.forecast.predicted_mw - left.forecast.predicted_mw,
    )
    .slice(0, 3);
  const focusZone = (zone: Zone) => {
    const map = mapRef.current;
    const bounds = L.geoJSON(
      zone.geometry as GeoJSON.GeoJsonObject,
    ).getBounds();
    if (map && bounds.isValid())
      map.fitBounds(bounds, { padding: [50, 50], maxZoom: 12 });
    onSelect(zone.id);
  };

  useEffect(() => {
    if (!containerRef.current || mapRef.current || !zones.length) return;
    const map = L.map(containerRef.current, {
      zoomControl: true,
      scrollWheelZoom: true,
      attributionControl: true,
    });
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "© OpenStreetMap contributors",
    }).addTo(map);
    layersRef.current = L.featureGroup().addTo(map);
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
      layersRef.current = null;
      didFitRef.current = false;
    };
  }, [zones.length]);

  useEffect(() => {
    const map = mapRef.current;
    const layers = layersRef.current;
    if (!map || !layers) return;
    layers.clearLayers();
    zones.forEach((zone) => {
      const forecast = forecastByZone.get(zone.id);
      const color = forecast ? MAP_COLORS[forecast.risk_level] : "#64748b";
      const layer = L.geoJSON(zone.geometry as GeoJSON.GeoJsonObject, {
        style: {
          color: selectedZoneId === zone.id ? "#d9f99d" : color,
          fillColor: color,
          fillOpacity: selectedZoneId === zone.id ? 0.72 : 0.42,
          weight: selectedZoneId === zone.id ? 3 : 1.5,
        },
      });
      const detail = forecast
        ? `<strong>${zone.name}</strong><br/>FortyGuard: ${number(forecast.temperature_c, 1)}°C<br/>EIA/ERCOT allocation: ${number(forecast.predicted_mw)} MW<br/>Risk: ${forecast.risk_level} (${number(forecast.risk_score, 1)}/100)`
        : `<strong>${zone.name}</strong><br/>Live forecast unavailable`;
      layer.bindTooltip(detail, { sticky: true, direction: "top" });
      layer.on("click", () => onSelect(zone.id));
      layer.addTo(layers);
    });
    priorityZones.forEach((item, index) => {
      const bounds = L.geoJSON(
        item.zone.geometry as GeoJSON.GeoJsonObject,
      ).getBounds();
      if (!bounds.isValid()) return;
      const marker = L.marker(bounds.getCenter(), {
        icon: L.divIcon({
          className: "",
          html: `<span style="display:grid;place-items:center;width:22px;height:22px;border-radius:999px;background:#0f172a;border:2px solid #d9f99d;color:#ecfccb;font:700 11px system-ui;box-shadow:0 2px 10px rgba(0,0,0,.45)">${index + 1}</span>`,
          iconSize: [22, 22],
          iconAnchor: [11, 11],
        }),
        interactive: true,
      });
      marker.bindTooltip(
        `Priority ${index + 1}: ${item.zone.name} · ${number(item.forecast.risk_score, 1)}/100`,
        { direction: "top" },
      );
      marker.on("click", () => onSelect(item.zone.id));
      marker.addTo(layers);
    });
    if (!didFitRef.current && layers.getLayers().length) {
      map.fitBounds(layers.getBounds(), { padding: [24, 24], maxZoom: 11 });
      didFitRef.current = true;
    }
  }, [zones, forecastByZone, onSelect, selectedZoneId]);

  if (!zones.length)
    return (
      <div className="rounded-2xl border border-white/10 p-6 text-slate-400">
        Map data is loading…
      </div>
    );

  return (
    <div className="overflow-hidden rounded-2xl border border-white/10 bg-[linear-gradient(160deg,rgba(15,23,42,.88),rgba(3,7,18,.94))]">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 px-5 py-4">
        <div>
          <p className="text-xs font-bold uppercase tracking-[.14em] text-slate-500">
            Interactive live risk map
          </p>
          <p className="mt-1 text-sm text-slate-300">
            Zoom with the controls or scroll; click a zone for its live insight.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {hottestZone && (
            <button
              onClick={() => focusZone(hottestZone.zone)}
              className="rounded-lg border border-white/15 px-2.5 py-1.5 text-xs font-semibold text-slate-200 hover:border-orange-300"
            >
              Focus hottest
            </button>
          )}
          {largestLoadZone && (
            <button
              onClick={() => focusZone(largestLoadZone.zone)}
              className="rounded-lg border border-white/15 px-2.5 py-1.5 text-xs font-semibold text-slate-200 hover:border-sky-300"
            >
              Focus largest load
            </button>
          )}
          <span className="rounded-full bg-emerald-400/10 px-2 py-1 text-xs text-emerald-200">
            {liveForecasts.length}/{zones.length} live forecasts
          </span>
        </div>
      </div>
      <div
        ref={containerRef}
        className={large ? "h-[460px] w-full" : "h-[340px] w-full"}
        aria-label="Interactive Houston operational-zone map"
      />
      <div className="grid gap-3 border-t border-white/10 bg-slate-950/50 p-4 sm:grid-cols-3">
        <MapInsight
          label="FortyGuard live heat"
          value={
            hottestZone
              ? `${hottestZone.zone.name} · ${number(hottestZone.forecast.temperature_c, 1)}°C`
              : "Awaiting zone samples"
          }
          detail="A live spatial-temperature sample is collected for each operational zone."
          tone="orange"
        />
        <MapInsight
          label="EIA/ERCOT load allocation"
          value={
            largestLoadZone
              ? `${largestLoadZone.zone.name} · ${number(largestLoadZone.forecast.predicted_mw)} MW`
              : "Awaiting city forecast"
          }
          detail="City demand is allocated by the configured zone weight and heat signal."
          tone="sky"
        />
        <MapInsight
          label="Selected zone"
          value={
            selectedZone && selectedForecast
              ? `${selectedZone.name} · ${selectedForecast.risk_level} risk`
              : "Click a map zone"
          }
          detail={
            selectedForecast
              ? `${number(selectedForecast.temperature_c, 1)}°C · ${number(selectedForecast.predicted_mw)} MW · score ${number(selectedForecast.risk_score, 1)}/100`
              : "A zone click opens its forecast details."
          }
          tone="lime"
        />
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-5 py-4 text-xs text-slate-400">
        <span className="inline-flex items-center gap-1.5">
          <i className="grid size-4 place-items-center rounded-full border border-lime-300 text-[9px] text-lime-200">
            1
          </i>
          Priority rank
        </span>
        <span className="font-semibold text-slate-300">Risk color</span>
        {[
          ["Low", "bg-emerald-400"],
          ["Watch", "bg-amber-400"],
          ["High", "bg-orange-400"],
          ["Critical", "bg-rose-400"],
        ].map(([label, color]) => (
          <span key={label} className="inline-flex items-center gap-1.5">
            <i className={`size-2 rounded-full ${color}`} />
            {label}
          </span>
        ))}
      </div>
    </div>
  );
}

function ZoneMap({
  zones,
  forecastByZone,
  selectedZoneId,
  onSelect,
  large = false,
}: {
  zones: Zone[];
  forecastByZone: Map<string, ZoneForecast>;
  selectedZoneId: string | null;
  onSelect: (id: string) => void;
  large?: boolean;
}) {
  const all = zones.flatMap((zone) => positions(zone.geometry.coordinates));
  if (!all.length)
    return (
      <div className="rounded-2xl border border-white/10 p-6 text-slate-400">
        Map data is loading…
      </div>
    );
  const west = Math.min(...all.map(([x]) => x));
  const east = Math.max(...all.map(([x]) => x));
  const south = Math.min(...all.map(([, y]) => y));
  const north = Math.max(...all.map(([, y]) => y));
  const width = Math.max(east - west, 0.01);
  const height = Math.max(north - south, 0.01);
  const liveForecasts = zones
    .map((zone) => ({ zone, forecast: forecastByZone.get(zone.id) }))
    .filter((item): item is { zone: Zone; forecast: ZoneForecast } =>
      Boolean(item.forecast),
    );
  const temperatures = liveForecasts.map((item) => item.forecast.temperature_c);
  const coldest = Math.min(...temperatures, 0);
  const hottest = Math.max(...temperatures, 0);
  const temperatureRange = Math.max(hottest - coldest, 0.1);
  const hottestZone = liveForecasts.reduce(
    (current, item) =>
      !current || item.forecast.temperature_c > current.forecast.temperature_c
        ? item
        : current,
    null as { zone: Zone; forecast: ZoneForecast } | null,
  );
  const largestLoadZone = liveForecasts.reduce(
    (current, item) =>
      !current || item.forecast.predicted_mw > current.forecast.predicted_mw
        ? item
        : current,
    null as { zone: Zone; forecast: ZoneForecast } | null,
  );
  const highestRisk = liveForecasts.reduce(
    (current, item) =>
      !current || item.forecast.risk_score > current.forecast.risk_score
        ? item
        : current,
    null as { zone: Zone; forecast: ZoneForecast } | null,
  );
  const mapUrl = `https://www.openstreetmap.org/export/embed.html?bbox=${(west - width * 0.12).toFixed(5)}%2C${(south - height * 0.12).toFixed(5)}%2C${(east + width * 0.12).toFixed(5)}%2C${(north + height * 0.12).toFixed(5)}&layer=mapnik`;
  const mapHeight = large ? "h-[440px]" : "h-[340px]";
  const point = ([x, y]: Position) =>
    [
      ((x - west) / width) * 88 + 6,
      ((north - y) / height) * 82 + 9,
    ] as Position;
  const path = (ring: Position[]) =>
    ring
      .map(
        (item, index) =>
          `${index ? "L" : "M"} ${point(item)[0].toFixed(2)} ${point(item)[1].toFixed(2)}`,
      )
      .join(" ") + " Z";
  return (
    <div
      className={`overflow-hidden rounded-2xl border border-white/10 bg-[radial-gradient(circle_at_80%_15%,rgba(56,189,248,.12),transparent_32%),linear-gradient(160deg,rgba(15,23,42,.88),rgba(3,7,18,.94))] ${large ? "min-h-[520px]" : "min-h-[420px]"}`}
    >
      <div className="flex items-center justify-between border-b border-white/10 px-5 py-4">
        <div>
          <p className="text-xs font-bold uppercase tracking-[.14em] text-slate-500">
            Live zone map
          </p>
          <p className="mt-1 text-sm text-slate-300">
            FortyGuard temperature + EIA/ERCOT load allocation in every zone
          </p>
        </div>
        <span className="rounded-full bg-emerald-400/10 px-2 py-1 text-xs text-emerald-200">
          {zones.length} active zones
        </span>
      </div>
      <div className="relative p-4">
        <iframe
          title="OpenStreetMap Houston basemap"
          src={mapUrl}
          className={`pointer-events-none absolute inset-4 ${mapHeight} w-[calc(100%-2rem)] rounded-lg border-0 opacity-80`}
          loading="lazy"
        />
        <svg
          className={`relative z-10 ${mapHeight} w-full drop-shadow-2xl`}
          viewBox="0 0 100 100"
          role="img"
          aria-label="Houston operational zone map"
        >
          <defs>
            <pattern
              id="grid"
              width="10"
              height="10"
              patternUnits="userSpaceOnUse"
            >
              <path
                d="M 10 0 L 0 0 0 10"
                fill="none"
                stroke="rgba(148,163,184,.12)"
                strokeWidth=".2"
              />
            </pattern>
          </defs>
          <rect width="100" height="100" fill="url(#grid)" />
          {zones.map((zone) => {
            const forecast = forecastByZone.get(zone.id);
            const ring = positions(zone.geometry.coordinates);
            const color = forecast
              ? MAP_COLORS[forecast.risk_level]
              : "#64748b";
            const heatStrength = forecast
              ? (forecast.temperature_c - coldest) / temperatureRange
              : 0;
            const fillOpacity = forecast ? 0.32 + heatStrength * 0.22 : 0.22;
            const [x, y] = point(centroid(ring));
            return (
              <g
                key={zone.id}
                className="cursor-pointer"
                onClick={() => onSelect(zone.id)}
              >
                <path
                  d={path(ring)}
                  fill={color}
                  fillOpacity={selectedZoneId === zone.id ? 0.78 : fillOpacity}
                  stroke={selectedZoneId === zone.id ? "#d9f99d" : color}
                  strokeWidth={selectedZoneId === zone.id ? 1.1 : 0.45}
                />
                <title>
                  {forecast
                    ? `${zone.name}: ${number(forecast.temperature_c, 1)}°C from FortyGuard; ${number(forecast.predicted_mw)} MW allocated EIA/ERCOT demand; ${forecast.risk_level} risk (${number(forecast.risk_score, 1)}/100)`
                    : `${zone.name}: live forecast unavailable`}
                </title>
                <text
                  x={x}
                  y={y - 1.4}
                  textAnchor="middle"
                  className="pointer-events-none fill-white text-[2.5px] font-bold"
                >
                  {zone.name.split(" ")[0]}
                </text>
                {forecast && (
                  <>
                    <text
                      x={x}
                      y={y + 1.2}
                      textAnchor="middle"
                      className="pointer-events-none fill-white text-[2px] font-semibold"
                    >
                      {number(forecast.temperature_c, 1)}°C
                    </text>
                    <text
                      x={x}
                      y={y + 3.6}
                      textAnchor="middle"
                      className="pointer-events-none fill-white text-[1.7px]"
                    >
                      {number(forecast.predicted_mw / 1000, 1)} GW
                    </text>
                  </>
                )}
              </g>
            );
          })}
        </svg>
      </div>
      <div className="grid gap-3 border-t border-white/10 bg-slate-950/50 p-4 sm:grid-cols-3">
        <MapInsight
          label="FortyGuard live heat"
          value={
            hottestZone
              ? `${hottestZone.zone.name} · ${number(hottestZone.forecast.temperature_c, 1)}°C`
              : "Awaiting zone samples"
          }
          detail="Zone color follows risk; darker fill means warmer relative conditions."
          tone="orange"
        />
        <MapInsight
          label="EIA/ERCOT load allocation"
          value={
            largestLoadZone
              ? `${largestLoadZone.zone.name} · ${number(largestLoadZone.forecast.predicted_mw)} MW`
              : "Awaiting city forecast"
          }
          detail="The city forecast is distributed using each operational zone's configured weight."
          tone="sky"
        />
        <MapInsight
          label="Current operational signal"
          value={
            highestRisk
              ? `${highestRisk.zone.name} · ${number(highestRisk.forecast.risk_score, 1)}/100 ${highestRisk.forecast.risk_level}`
              : "No completed zone forecast"
          }
          detail="Click a zone for its source-backed forecast and risk detail."
          tone="lime"
        />
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-5 pb-4 text-xs text-slate-400">
        <span className="font-semibold text-slate-300">Risk color</span>
        {[
          ["Low", "bg-emerald-400"],
          ["Watch", "bg-amber-400"],
          ["High", "bg-orange-400"],
          ["Critical", "bg-rose-400"],
        ].map(([label, color]) => (
          <span key={label} className="inline-flex items-center gap-1.5">
            <i className={`size-2 rounded-full ${color}`} />
            {label}
          </span>
        ))}
      </div>
    </div>
  );
}
function MapInsight({
  label,
  value,
  detail,
  tone,
}: {
  label: string;
  value: string;
  detail: string;
  tone: "lime" | "sky" | "orange";
}) {
  const textColor = {
    lime: "text-lime-200",
    sky: "text-sky-200",
    orange: "text-orange-200",
  }[tone];
  return (
    <div className="rounded-xl border border-white/10 bg-white/[.035] p-3">
      <p className="text-[10px] font-bold uppercase tracking-[.12em] text-slate-500">
        {label}
      </p>
      <p className={`mt-1 text-sm font-bold ${textColor}`}>{value}</p>
      <p className="mt-1 text-xs leading-5 text-slate-400">{detail}</p>
    </div>
  );
}
function positions(value: unknown): Position[] {
  if (!Array.isArray(value)) return [];
  if (
    value.length >= 2 &&
    typeof value[0] === "number" &&
    typeof value[1] === "number"
  )
    return [[value[0], value[1]]];
  return value.flatMap(positions);
}
function centroid(points: Position[]): Position {
  const total = points.reduce(
    ([x, y], [a, b]) => [x + a, y + b] as Position,
    [0, 0],
  );
  return points.length
    ? [total[0] / points.length, total[1] / points.length]
    : [0, 0];
}
function Banner({
  tone,
  text,
  onClose,
}: {
  tone: "error" | "success";
  text: string;
  onClose: () => void;
}) {
  return (
    <div
      className={`mb-5 flex items-center justify-between gap-4 rounded-xl border px-4 py-3 text-sm ${tone === "error" ? "border-red-400/40 bg-red-400/10 text-red-100" : "border-emerald-400/40 bg-emerald-400/10 text-emerald-100"}`}
    >
      <span>{text}</span>
      <button onClick={onClose}>Dismiss</button>
    </div>
  );
}
function Metric({
  label,
  value,
  detail,
  accent,
}: {
  label: string;
  value: string;
  detail: string;
  accent: "lime" | "sky" | "orange" | "violet";
}) {
  const colors = {
    lime: "text-lime-200",
    sky: "text-sky-200",
    orange: "text-orange-200",
    violet: "text-violet-200",
  };
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[.035] p-5">
      <p className="text-[10px] font-bold uppercase tracking-[.14em] text-slate-500">
        {label}
      </p>
      <p className={`mt-3 text-2xl font-bold tracking-tight ${colors[accent]}`}>
        {value}
      </p>
      <p className="mt-2 text-xs text-slate-400">{detail}</p>
    </div>
  );
}
function RiskBadge({ risk }: { risk?: string }) {
  return (
    <span
      className={`h-fit rounded-full border px-2.5 py-1 text-xs font-bold capitalize ${RISK_CLASSES[risk ?? "low"]}`}
    >
      {risk ?? "unavailable"}
    </span>
  );
}
function Gate({ ready, label }: { ready: boolean; label: string }) {
  return (
    <div className="mt-3 flex items-center gap-3 text-sm">
      <span
        className={`grid size-5 place-items-center rounded-full text-xs ${ready ? "bg-emerald-400/15 text-emerald-200" : "bg-slate-700/70 text-slate-400"}`}
      >
        {ready ? "✓" : "–"}
      </span>
      <span className={ready ? "text-slate-200" : "text-slate-400"}>
        {label}
      </span>
    </div>
  );
}
function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-black/15 p-2">
      <p className="text-[10px] uppercase tracking-wide text-slate-500">
        {label}
      </p>
      <p className="mt-1 text-lg font-bold">{value}</p>
    </div>
  );
}
function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-white/10 bg-black/15 p-3">
      <p className="text-[10px] uppercase tracking-wide text-slate-500">
        {label}
      </p>
      <p className="mt-1 text-sm font-bold capitalize">{value}</p>
    </div>
  );
}
