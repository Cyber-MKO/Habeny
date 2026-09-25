import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useMetricsSocket } from "../ws";
import { StatCard, PageHeader, Pill, DataTable, Spinner } from "../components/UI";
import { formatDateTime, t } from "../i18n";

const ACTIVITY_REFRESH_MS = 30000;
const SIEM_LABELS = { wazuh: "Wazuh", ossec: "OSSEC", utmstack: "UTMstack", elastic: "Elastic" };

function formatUptime(seconds) {
  if (seconds == null) return "—";
  const d = Math.floor(seconds / 86400), h = Math.floor((seconds % 86400) / 3600), m = Math.floor((seconds % 3600) / 60);
  if (d) return `${d}d ${h}h`;
  if (h) return `${h}h ${m}m`;
  return `${m}m`;
}

// Usage color: green, orange past `warn`, red past `bad`
const level = (value, warn, bad) => (value == null ? undefined : value > bad ? "red" : value > warn ? "orange" : "green");

function lastDetection(d) {
  if (!d) return "—";
  return `${d.detected ?? 0}/${d.containers ?? 0} (${d.detection_rate ?? 0}%) · ${d.profile_id} · ${formatDateTime(d.checked_at)}`;
}

// Details about the server that rarely matter, loaded when opened
function ServerDetails() {
  const [info, setInfo] = useState(null);
  const [error, setError] = useState(null);
  const load = () => {
    if (info) return;
    api.getSystemInfo().then((r) => setInfo(r.data)).catch((e) => setError(e.message));
  };
  const p = info?.platform || {};
  const s = info?.system || {};
  const f = info?.supported_features || {};
  const rows = info && [
    [t("Version"), p.version],
    [t("LXC Version"), p.lxc_version],
    [t("Architecture"), s.arch],
    [t("Running as root"), s.is_root ? t("Yes") : t("No")],
    [t("CPU Count"), s.cpu_count],
    [t("Deploy Workers"), s.worker_config?.deploy_workers],
    [t("Benchmark Workers"), s.worker_config?.benchmark_workers],
    [t("LXC Config Path"), p.default_config_path],
    [t("SIEM Types"), (f.siem_types || []).join(", ")],
    [t("OS Types"), (f.os_types || []).join(", ")],
    [t("Simulation Profiles"), (f.simulation_profiles || []).join(", ")],
    [t("LXC Templates"), (info.templates || []).join(", ")],
  ];
  return (
    <details className="card server-details" onToggle={(e) => e.currentTarget.open && load()}>
      <summary className="section-title">{t("Server details")}</summary>
      {error ? <p className="muted">{t("Failed to load system info:")} {error}</p> : !info ? <Spinner /> : (
        <dl className="details">
          {rows.map(([label, value]) => (
            <div className="details-row" key={label}><dt>{label}</dt><dd>{value ?? "—"}</dd></div>
          ))}
        </dl>
      )}
    </details>
  );
}

export default function Dashboard() {
  const { metrics, connected } = useMetricsSocket();
  const [health, setHealth] = useState(null);
  const [stats, setStats] = useState(null);
  const [alerts, setAlerts] = useState(null);
  const [siems, setSiems] = useState(null);
  const [siemsLoading, setSiemsLoading] = useState(false);
  const [activity, setActivity] = useState(null);

  // Initial snapshot, shown until the first live metrics message arrives
  useEffect(() => {
    api.getAgentsStats().then((r) => setStats(r.data)).catch(() => setStats(null));
  }, []);

  const loadSiems = useCallback(() => {
    setSiemsLoading(true);
    api.getSiemSummary().then((r) => setSiems(r.data?.siems || [])).catch(() => setSiems((s) => s || []))
      .finally(() => setSiemsLoading(false));
  }, []);
  useEffect(() => { loadSiems(); }, [loadSiems]);

  // Status, alerts and activity change without a live message: poll them while the page is visible
  const poll = useCallback(() => {
    if (document.hidden) return;
    api.getHealth().then(setHealth).catch(() => setHealth(null));
    api.getAlerts().then((r) => setAlerts(r.data?.alerts || [])).catch(() => setAlerts((a) => a || []));
    api.getActivity({ limit: 5 }).then((r) => setActivity(r.data?.logs || [])).catch(() => setActivity((a) => a || []));
  }, []);
  useEffect(() => {
    poll();
    const timer = setInterval(poll, ACTIVITY_REFRESH_MS);
    return () => clearInterval(timer);
  }, [poll]);

  // Live numbers win once they arrive; the snapshot only fills the gap before that
  const source = metrics || stats || {};
  const byStatus = source.by_status || {};
  const total = source.total_agents;
  const sys = metrics?.system || {};
  const pending = (v) => (v ?? "—");
  const degraded = health?.status === "degraded";
  const load1 = sys.load_average?.[0];

  const siemColumns = [
    { key: "siem_type", label: "SIEM", render: (r) => SIEM_LABELS[r.siem_type] || r.siem_type },
    { key: "containers", label: t("Containers"), render: (r) => `${r.containers} (${t("{count} running", { count: r.running })})` },
    { key: "agents_running", label: t("Agent running"), render: (r) => `${r.agents_running}/${r.containers}` },
    { key: "manager_reachable", label: t("Reaches manager"), render: (r) => `${r.manager_reachable}/${r.containers}` },
    { key: "last_detection", label: t("Latest detection check"), render: (r) => lastDetection(r.last_detection) },
  ];

  return (
    <>
      <PageHeader title={t("Dashboard")} subtitle={t("Fleet, host and SIEMs at a glance")}>
        {connected && <span className="live-dot" title={t("Live updates active")} />}
      </PageHeader>

      {alerts?.length > 0 && (
        <section className="section" aria-labelledby="dashboard-alerts">
          <h2 className="section-title" id="dashboard-alerts">{t("Active alerts")}</h2>
          <div className="card">
            <ul className="alert-list">
              {alerts.slice(0, 5).map((a) => (
                <li key={`${a.name}:${a.target || ""}`} className={`alert-item alert-${a.severity}`}>
                  <div className="alert-head">
                    <Pill status={a.severity} />
                    <strong>{a.label}{a.target ? ` (${a.target})` : ""}</strong>
                  </div>
                  <p>{a.message}</p>
                </li>
              ))}
            </ul>
            <Link to="/monitoring">{alerts.length > 5 ? t("All {count} alerts on Monitoring", { count: alerts.length }) : t("Details on Monitoring")}</Link>
          </div>
        </section>
      )}

      <section className="section" aria-labelledby="dashboard-fleet">
        <h2 className="section-title" id="dashboard-fleet">{t("Fleet")}</h2>
        <div className="stats-grid">
          <StatCard label={t("Total Containers")} value={pending(total)} color="blue" />
          <StatCard label={t("Running")} value={pending(byStatus.running)} color="green" />
          <StatCard label={t("Stopped")} value={pending(byStatus.stopped)} color={byStatus.stopped > 0 ? "orange" : undefined} />
          <StatCard label={t("Active Simulations")} value={pending(metrics?.active_simulations ?? health?.system_info?.active_simulations)} color="orange"
            meta={metrics?.current_eps_target ? t("{eps} events/s target", { eps: metrics.current_eps_target }) : undefined} />
        </div>
      </section>

      <section className="section" aria-labelledby="dashboard-host">
        <h2 className="section-title" id="dashboard-host">{t("Host")}</h2>
        <div className="stats-grid">
          <StatCard label={t("Platform Status")} value={health ? (degraded ? t("Degraded") : t("Healthy")) : "—"}
            color={!health ? undefined : degraded ? "red" : "green"}
            meta={health ? t("Version {version} · up {uptime}", { version: health.version, uptime: formatUptime(health.uptime_seconds) }) : undefined} />
          <StatCard label={t("CPU Load (1m)")} value={load1 == null ? "—" : load1.toFixed(2)}
            color={load1 == null || !sys.cpu_count ? undefined : level(load1 / sys.cpu_count, 0.7, 1)}
            meta={sys.cpu_count ? t("{count} cores", { count: sys.cpu_count }) : undefined} />
          <StatCard label={t("Memory Used")} value={sys.memory_used_percent == null ? "—" : `${sys.memory_used_percent}%`}
            color={level(sys.memory_used_percent, 70, 85)}
            meta={sys.memory_available_mb != null ? t("{mb} MB free", { mb: sys.memory_available_mb }) : undefined} />
          <StatCard label={t("Disk Used")} value={sys.disk_used_percent == null ? "—" : `${sys.disk_used_percent}%`}
            color={level(sys.disk_used_percent, 80, 90)} />
        </div>
      </section>

      <section className="section" aria-labelledby="dashboard-siems">
        <div className="section-head">
          <h2 className="section-title" id="dashboard-siems">{t("SIEMs")}</h2>
          <button className="btn btn-sm btn-secondary" onClick={loadSiems} disabled={siemsLoading}>{siemsLoading ? t("Refreshing…") : t("Refresh")}</button>
        </div>
        <div className="card">
          {siems === null ? <Spinner /> : (
            <DataTable columns={siemColumns} rows={siems} label={t("SIEMs")}
              emptyMsg={t("No SIEM agents deployed yet, and no detection checks.")} />
          )}
          <p className="account-help" style={{ marginTop: 12 }}>
            {t("Agent running and Reaches manager come from each container's own check. Detection checks ask the SIEM what it detected after an attack simulation.")}
          </p>
        </div>
      </section>

      <div className="dashboard-split">
        <div className="card">
          <div className="section-title">{t("Quick Actions")}</div>
          <div className="btn-group" style={{ flexWrap: "wrap" }}>
            <Link to="/deploy" className="btn btn-primary">{t("Deploy Containers")}</Link>
            <Link to="/simulations" className="btn btn-secondary">{t("Start Simulation")}</Link>
            <Link to="/reports" className="btn btn-secondary">{t("Generate Report")}</Link>
            <Link to="/logs" className="btn btn-secondary">{t("Upload Logs")}</Link>
          </div>
        </div>

        <div className="card">
          <div className="section-title">{t("Recent Activity")}</div>
          {activity === null ? <div className="empty" style={{ padding: 16 }}><p>{t("Loading…")}</p></div>
            : activity.length === 0 ? <div className="empty" style={{ padding: 16 }}><p>{t("No recent activity")}</p></div> : (
            <table>
              <tbody>
                {activity.map((a, i) => (
                  <tr key={`${a.timestamp}-${i}`}>
                    <td style={{ fontSize: 11, color: "var(--text-muted)", whiteSpace: "nowrap" }}>{a.timestamp ? new Date(a.timestamp).toLocaleTimeString() : ""}</td>
                    <td>{a.action}</td>
                    <td><Pill status={a.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      <ServerDetails />
    </>
  );
}
