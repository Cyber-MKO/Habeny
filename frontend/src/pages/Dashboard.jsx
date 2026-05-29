import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useMetricsSocket } from "../ws";
import { StatCard, PageHeader, Spinner, Pill } from "../components/UI";

export default function Dashboard() {
  const { metrics, connected } = useMetricsSocket();
  const [health, setHealth] = useState(null);
  const [stats, setStats] = useState(null);
  const [activity, setActivity] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      api.getHealth().catch(() => null),
      api.getAgentsStats().catch(() => null),
      api.getActivity({ limit: 5 }).catch(() => null),
    ]).then(([h, s, a]) => {
      setHealth(h);
      setStats(s);
      setActivity(a?.data?.logs || []);
    }).finally(() => setLoading(false));
  }, []);

  const live = metrics || {};
  const byStatus = stats?.data?.by_status || live.by_status || {};
  const bySiem = stats?.data?.by_siem_type || live.by_siem_type || {};
  const total = stats?.data?.total_agents ?? live.total_agents ?? 0;
  const errors = byStatus.error ?? 0;

  if (loading) return <Spinner />;

  return (
    <>
      <PageHeader title="Dashboard" subtitle="Real-time platform overview">
        {connected && <span className="live-dot" title="Live updates active" />}
      </PageHeader>

      <div className="stats-grid">
        <StatCard label="Total Containers" value={total} color="blue" meta={Object.entries(bySiem).map(([k, v]) => `${k}: ${v}`).join(" · ") || "—"} />
        <StatCard label="Running" value={byStatus.running ?? 0} color="green" />
        <StatCard label="Stopped" value={byStatus.stopped ?? 0} color="red" />
        <StatCard label="Errors" value={errors} color={errors > 0 ? "red" : undefined} />
        <StatCard label="Active Simulations" value={live.active_simulations ?? health?.system_info?.active_simulations ?? 0} color="orange" />
        <StatCard label="Platform Status" value={health?.status === "healthy" ? "Healthy" : "Unknown"} color={health?.status === "healthy" ? "green" : "red"} />
        <StatCard label="CPU Cores" value={health?.system_info?.cpu_count ?? "—"} />
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

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
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
          {activity.length === 0 ? <div className="empty" style={{ padding: 16 }}><p>No recent activity</p></div> : (
            <table>
              <tbody>
                {activity.map((a, i) => (
                  <tr key={i}>
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
