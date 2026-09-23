import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { useStore } from "../store";
import { PageHeader, StatCard, Spinner } from "../components/UI";

function formatUptime(seconds) {
  if (seconds == null) return "—";
  const d = Math.floor(seconds / 86400), h = Math.floor((seconds % 86400) / 3600), m = Math.floor((seconds % 3600) / 60);
  if (d) return `${d}d ${h}h`;
  if (h) return `${h}h ${m}m`;
  return `${m}m`;
}

export default function SystemInfo() {
  const { toast } = useStore();
  const [info, setInfo] = useState(null);
  const [error, setError] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [updatedAt, setUpdatedAt] = useState(null);

  // Keeps the current numbers on screen while refreshing instead of blanking the page
  const load = useCallback(async () => {
    setRefreshing(true);
    try {
      const res = await api.getSystemInfo();
      if (!res.success) throw new Error(res.error || res.message);
      setInfo(res.data);
      setError(null);
      setUpdatedAt(new Date());
    } catch (err) {
      setError(err.message);
      toast(`System info: ${err.message}`, "error");
    } finally {
      setRefreshing(false);
    }
  }, [toast]);
  useEffect(() => { load(); }, [load]);

  if (!info) {
    if (!error) return <Spinner />;
    return (
      <div className="empty">
        <p>Failed to load system info: {error}</p>
        <button className="btn btn-secondary" onClick={load} disabled={refreshing}>Retry</button>
      </div>
    );
  }

  const p = info.platform || {};
  const s = info.system || {};
  const c = info.containers || {};
  const f = info.supported_features || {};
  const byState = c.by_state || {};

  return (
    <>
      <PageHeader
        title="System Info"
        subtitle={updatedAt ? `Platform and LXC configuration · updated ${updatedAt.toLocaleTimeString()}` : "Platform and LXC configuration"}
      >
        <button className="btn btn-secondary" onClick={load} disabled={refreshing}>
          {refreshing ? "Refreshing…" : "Refresh"}
        </button>
      </PageHeader>

      <div className="section">
        <div className="section-title">Platform</div>
        <div className="stats-grid">
          <StatCard label="Version" value={p.version || "—"} />
          <StatCard label="Uptime" value={formatUptime(p.uptime_seconds)} meta="Since the API server started" />
          <StatCard label="LXC Version" value={p.lxc_version || "—"} />
          <StatCard label="Config Path" value={p.default_config_path || "—"} />
        </div>
      </div>

      <div className="section">
        <div className="section-title">System</div>
        <div className="stats-grid">
          <StatCard label="Architecture" value={s.arch || "—"} />
          <StatCard label="Root" value={s.is_root ? "Yes" : "No"} color={s.is_root ? "green" : "red"} />
          <StatCard label="CPU Count" value={s.cpu_count ?? "—"} />
          <StatCard label="Thread Workers" value={s.worker_config?.thread_workers ?? "—"} />
          <StatCard label="Process Workers" value={s.worker_config?.process_workers ?? "—"} />
        </div>
      </div>

      <div className="section">
        <div className="section-title">Containers</div>
        <div className="stats-grid">
          <StatCard label="Total" value={c.total ?? 0} color="blue" />
          <StatCard label="Running" value={byState.RUNNING ?? 0} color="green" />
          <StatCard label="Stopped" value={byState.STOPPED ?? 0} color="red" />
          <StatCard label="Frozen" value={byState.FROZEN ?? 0} color="cyan" />
          {byState.OTHER > 0 && <StatCard label="Other" value={byState.OTHER} meta="Starting, stopping or aborting" />}
        </div>
      </div>

      <div className="section">
        <div className="section-title">Supported Features</div>
        <div className="card">
          <table>
            <tbody>
              <tr><td style={{fontWeight:600,width:180}}>SIEM Types</td><td>{(f.siem_types||[]).join(", ")}</td></tr>
              <tr><td style={{fontWeight:600}}>OS Types</td><td>{(f.os_types||[]).join(", ")}</td></tr>
              <tr><td style={{fontWeight:600}}>Simulation Profiles</td><td>{(f.simulation_profiles||[]).join(", ")}</td></tr>
              <tr><td style={{fontWeight:600}}>Parallel Modes</td><td>{(f.parallel_modes||[]).join(", ")}</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      {info.templates?.length > 0 && (
        <div className="section">
          <div className="section-title">LXC Templates</div>
          <div className="card"><pre className="json-block">{(info.templates||[]).join("\n")}</pre></div>
        </div>
      )}
    </>
  );
}
