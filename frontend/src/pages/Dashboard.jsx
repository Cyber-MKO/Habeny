import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useMetricsSocket } from "../ws";
import { StatCard, PageHeader, Pill } from "../components/UI";

const ACTIVITY_REFRESH_MS = 30000;

export default function Dashboard() {
  const { metrics, connected } = useMetricsSocket();
  const [health, setHealth] = useState(null);
  const [stats, setStats] = useState(null);
  const [activity, setActivity] = useState(null);

  // Initial snapshot, shown until the first live metrics message arrives
  useEffect(() => {
    api.getHealth().then(setHealth).catch(() => setHealth(null));
    api.getAgentsStats().then((r) => setStats(r.data)).catch(() => setStats(null));
  }, []);

  const loadActivity = useCallback(() => {
    if (document.hidden) return;
    api.getActivity({ limit: 5 }).then((r) => setActivity(r.data?.logs || [])).catch(() => setActivity((a) => a || []));
  }, []);
  useEffect(() => {
    loadActivity();
    const t = setInterval(loadActivity, ACTIVITY_REFRESH_MS);
    return () => clearInterval(t);
  }, [loadActivity]);

  // Live numbers win once they arrive; the snapshot only fills the gap before that
  const source = metrics || stats || {};
  const byStatus = source.by_status || {};
  const bySiem = source.by_siem_type || {};
  const total = source.total_agents;
  const errors = byStatus.error ?? 0;
  const pending = (v) => (v ?? "—");

  return (
    <>
      <PageHeader title="Dashboard" subtitle="Real-time platform overview">
        {connected && <span className="live-dot" title="Live updates active" />}
      </PageHeader>

      <div className="stats-grid">
        <StatCard label="Total Containers" value={pending(total)} color="blue" meta={Object.entries(bySiem).map(([k, v]) => `${k}: ${v}`).join(" · ") || "—"} />
        <StatCard label="Running" value={pending(byStatus.running)} color="green" />
        <StatCard label="Stopped" value={pending(byStatus.stopped)} color="red" />
        <StatCard label="Errors" value={errors} color={errors > 0 ? "red" : undefined} />
        <StatCard label="Active Simulations" value={pending(metrics?.active_simulations ?? health?.system_info?.active_simulations)} color="orange" />
        <StatCard label="Platform Status" value={health?.status === "healthy" || connected ? "Healthy" : health ? "Unknown" : "—"} color={health?.status === "healthy" || connected ? "green" : "red"} />
        <StatCard label="CPU Cores" value={pending(metrics?.system?.cpu_count ?? health?.system_info?.cpu_count)} />
        <StatCard label="WebSocket" value={connected ? "Connected" : "Disconnected"} color={connected ? "green" : "red"} />
      </div>

      {bySiem && Object.keys(bySiem).length > 0 && (
        <div className="section">
          <div className="section-title">Containers by SIEM Type</div>
          <div className="stats-grid">
            {Object.entries(bySiem).map(([type, count]) => (
              <StatCard key={type} label={type} value={count} />
            ))}
          </div>
        </div>
      )}

      <div className="dashboard-split">
        <div className="card">
          <div className="section-title">Quick Actions</div>
          <div className="btn-group" style={{ flexWrap: "wrap" }}>
            <Link to="/deploy" className="btn btn-primary">Deploy Containers</Link>
            <Link to="/simulations" className="btn btn-secondary">Start Simulation</Link>
            <Link to="/reports" className="btn btn-secondary">Generate Report</Link>
            <Link to="/logs" className="btn btn-secondary">Upload Logs</Link>
          </div>
        </div>

        <div className="card">
          <div className="section-title">Recent Activity</div>
          {activity === null ? <div className="empty" style={{ padding: 16 }}><p>Loading…</p></div>
            : activity.length === 0 ? <div className="empty" style={{ padding: 16 }}><p>No recent activity</p></div> : (
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
    </>
  );
}
