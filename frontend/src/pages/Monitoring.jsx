import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { useStore } from "../store";
import { useAuth } from "../auth";
import { NavLink } from "react-router-dom";
import { Details } from "../components/Details";
import { Empty, PageHeader, Pill, Spinner, StatCard } from "../components/UI";
import { formatDateTime, t } from "../i18n";

const HISTORY = [
  { name: "cpu_load_1m", title: t("CPU load, 1 minute"), label: t("Load"), color: "var(--cyan)" },
  { name: "memory_used_percent", title: t("Memory used (%)"), label: t("Mem%"), color: "var(--orange)" },
  { name: "disk_used_percent", title: t("Disk used (%)"), label: t("Disk%"), color: "var(--accent)" },
  { name: "containers_running", title: t("Running containers"), label: t("Running"), color: "var(--green)" },
];

function MiniChart({ data, label, color = "var(--accent)", height = 60 }) {
  if (!data || data.length < 2) return <div className="empty" style={{ padding: 8 }}><p>{t("Collecting data...")}</p></div>;
  const values = data.map((d) => d.value);
  const max = Math.max(...values) || 1;
  const min = Math.min(...values);
  const w = 100 / values.length;
  return (
    <div style={{ position: "relative", height }}>
      <svg viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" style={{ width: "100%", height: "100%" }} role="img"
        aria-label={t("{label}: latest {latest}, lowest {min}, highest {max}", { label, latest: values[values.length - 1]?.toFixed(1), min: min.toFixed(1), max: max.toFixed(1) })}>
        <polyline
          fill="none"
          stroke={color}
          strokeWidth="1.5"
          points={values.map((v, i) => `${i * w + w / 2},${height - ((v - min) / (max - min || 1)) * (height - 4) - 2}`).join(" ")}
        />
      </svg>
      <div style={{ position: "absolute", bottom: 0, right: 0, fontSize: 10, color: "var(--text-muted)" }}>
        {label}: {values[values.length - 1]?.toFixed(1)}
      </div>
    </div>
  );
}

// Deployment speed, API latency and simulation totals, and the host's history
function Performance() {
  const { toast } = useStore();
  const [perf, setPerf] = useState(null);
  const [history, setHistory] = useState({});
  const load = useCallback(async () => {
    try {
      const empty = { data: { metrics: [] } };
      const [b, ...series] = await Promise.all([
        api.getBenchmarks(),
        ...HISTORY.map((h) => api.getMetricsHistory({ metric_type: "system", metric_name: h.name, limit: 100 }).catch(() => empty)),
      ]);
      setPerf(b.data || {});
      setHistory(Object.fromEntries(HISTORY.map((h, i) => [h.name, (series[i].data?.metrics || []).reverse()])));
    } catch (e) { toast(e.message, "error"); setPerf((p) => p || {}); }
  }, [toast]);
  useEffect(() => {
    load();
    const timer = setInterval(load, 30000);
    return () => clearInterval(timer);
  }, [load]);

  if (!perf) return <Spinner />;
  const dep = perf.deployment || {};
  const dt = dep.deploy_time_seconds || {};
  const lat = perf.api_latency_ms?.deploy_endpoint || {};
  const sim = perf.simulations || {};
  return (
    <>
      <section className="section" aria-labelledby="history-title">
        <h2 className="section-title" id="history-title">{t("Host history")}</h2>
        <div className="chart-grid">
          {HISTORY.map((h) => (
            <div className="card" key={h.name}>
              <div className="section-title">{h.title}</div>
              <MiniChart data={history[h.name]} label={h.label} color={h.color} />
            </div>
          ))}
        </div>
      </section>

      <section className="section" aria-labelledby="deploy-perf-title">
        <h2 className="section-title" id="deploy-perf-title">{t("Deployments")}</h2>
        <div className="stats-grid">
          <StatCard label={t("Total Deployments")} value={dep.total_deploys ?? 0} color="blue" />
          <StatCard label={t("Success Rate")} value={`${dep.success_rate_percent ?? 0}%`} color={dep.success_rate_percent >= 90 ? "green" : "orange"} />
          <StatCard label={t("Avg Deploy Time")} value={`${dt.avg ?? 0}s`} meta={`P50: ${dt.p50 ?? 0}s`} />
          <StatCard label={t("P90 Deploy Time")} value={`${dt.p90 ?? 0}s`} color={dt.p90 > 300 ? "red" : "green"} meta={`P99: ${dt.p99 ?? 0}s`} />
          <StatCard label={t("Deploy API latency")} value={`${lat.avg ?? 0}ms`} meta={`P50 ${lat.p50 ?? 0} · P90 ${lat.p90 ?? 0} · P99 ${lat.p99 ?? 0} ms`}
            color={lat.p99 > 10000 ? "red" : lat.p90 > 5000 ? "orange" : undefined} />
        </div>
      </section>

      <section className="section" aria-labelledby="sim-perf-title">
        <h2 className="section-title" id="sim-perf-title">{t("Simulations")}</h2>
        <div className="stats-grid">
          <StatCard label={t("Total Events")} value={(sim.total_events_generated ?? 0).toLocaleString()} color="cyan" />
          <StatCard label={t("Completed Sims")} value={sim.completed ?? 0} color="green" />
          <StatCard label={t("Failed Sims")} value={sim.failed ?? 0} color={sim.failed > 0 ? "red" : undefined} />
        </div>
      </section>
    </>
  );
}

const PROMETHEUS = (origin) => `scrape_configs:
  - job_name: habeny
    scheme: ${origin.startsWith("https") ? "https" : "http"}
    tls_config: {insecure_skip_verify: true}   # only with Habeny's self-signed certificate
    authorization: {credentials_file: /etc/prometheus/habeny.token}
    static_configs: [{targets: ["${origin.replace(/^https?:\/\//, "")}"]}]`;

const RULES = `groups:
  - name: habeny
    rules:
      - alert: HabenyDown
        expr: up{job="habeny"} == 0
        for: 2m
      - alert: HabenyAlert        # anything Habeny itself raises (disk, LXC, backups, deploys)
        expr: habeny_alerts_active == 1
        labels: {severity: "{{ $labels.severity }}"}
        annotations: {summary: "Habeny: {{ $labels.alert }} {{ $labels.target }}"}
      - alert: HabenyDeploymentsFailing
        expr: increase(habeny_containers_deployed_total{result="failure"}[1h]) > 0
      - alert: HabenyNoRecentBackup
        expr: time() - habeny_backup_last_timestamp_seconds > 2 * 86400`;

export default function Monitoring() {
  const { user } = useAuth();
  const { toast } = useStore();
  const [alerts, setAlerts] = useState(null);

  const load = useCallback(async () => {
    try { setAlerts((await api.getAlerts()).data.alerts); }
    catch (err) { toast(err.message, "error"); setAlerts([]); }
  }, [toast]);
  useEffect(() => {
    load();
    const timer = setInterval(load, 30000);
    return () => clearInterval(timer);
  }, [load]);

  const origin = window.location.origin;
  return (
    <>
      <PageHeader title={t("Monitoring")} subtitle={t("Alerts, history and performance, and endpoints for external monitoring")}>
        <button className="btn btn-secondary" onClick={load}>{t("Refresh")}</button>
      </PageHeader>

      <section className="section" aria-labelledby="alerts-title">
        <h2 className="section-title" id="alerts-title">{t("Active alerts")}</h2>
        <div className="card">
          {alerts === null ? <Spinner /> : !alerts.length ? <Empty message={t("No active alerts. Disk space, LXC, backups and deployments are fine.")} /> : (
            <ul className="alert-list">
              {alerts.map((a) => (
                <li key={`${a.name}:${a.target || ""}`} className={`alert-item alert-${a.severity}`}>
                  <div className="alert-head">
                    <Pill status={a.severity} />
                    <strong>{a.label}{a.target ? ` (${a.target})` : ""}</strong>
                    <span className="muted">{t("since")} {formatDateTime(a.since)}</span>
                  </div>
                  <p>{a.message}</p>
                  {Object.keys(a.details || {}).length > 0 && <Details data={a.details} />}
                </li>
              ))}
            </ul>
          )}
        </div>
        {user.is_admin && (
          <p className="account-help">
            {t("Alerts are also sent to")} <NavLink to="/notifications">{t("notification channels")}</NavLink> {t("when they start and clear.")}
          </p>
        )}
      </section>

      <Performance />

      <section className="section" aria-labelledby="endpoints-title">
        <h2 className="section-title" id="endpoints-title">{t("Endpoints for monitoring systems")}</h2>
        <div className="card">
          <dl className="details">
            <div className="details-row"><dt><code>GET /api/healthz</code></dt><dd>{t("Liveness: 200 while the server answers. No sign-in.")}</dd></div>
            <div className="details-row"><dt><code>GET /api/readyz</code></dt><dd>{t("Readiness: 200 when the database, LXC and disk are fine, 503 otherwise. No sign-in.")}</dd></div>
            <div className="details-row"><dt><code>GET /api/metrics</code></dt><dd>{t("Prometheus metrics. Needs an API token (the viewer role is enough).")}</dd></div>
          </dl>
        </div>
      </section>

      <section className="section" aria-labelledby="prom-title">
        <h2 className="section-title" id="prom-title">Prometheus</h2>
        <div className="card">
          <p className="account-help">
            {t("Create a viewer")} <NavLink to="/account">{t("API token")}</NavLink>{t(", save it in")} <code>/etc/prometheus/habeny.token</code>{t(", then scrape:")}
          </p>
          <pre className="code-sample" tabIndex={0} aria-label={t("Prometheus scrape configuration")}>{PROMETHEUS(origin)}</pre>
          <p className="account-help">{t("Example alerting rules:")}</p>
          <pre className="code-sample" tabIndex={0} aria-label={t("Example alerting rules")}>{RULES}</pre>
        </div>
      </section>
    </>
  );
}
