import { useEffect, useState } from "react";
import { api } from "../api";
import { PageHeader, StatCard, Spinner, JsonBlock } from "../components/UI";

export default function SystemInfo() {
  const [info, setInfo] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try { const res = await api.getSystemInfo(); setInfo(res.data); } catch {}
    setLoading(false);
  };
  useEffect(() => { load(); }, []);

  if (loading) return <Spinner />;
  if (!info) return <div className="empty"><p>Failed to load system info</p></div>;

  const p = info.platform || {};
  const s = info.system || {};
  const c = info.containers || {};
  const f = info.supported_features || {};
  const byState = c.by_state || {};

  return (
    <>
      <PageHeader title="System Info" subtitle="Platform and LXC configuration">
        <button className="btn btn-secondary" onClick={load}>Refresh</button>
      </PageHeader>

      <div className="section">
        <div className="section-title">Platform</div>
        <div className="stats-grid">
          <StatCard label="Name" value={p.name || "—"} />
          <StatCard label="Version" value={p.version || "—"} />
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

      {info.templates && (
        <div className="section">
          <div className="section-title">LXC Templates</div>
          <div className="card"><pre className="json-block">{(info.templates||[]).join("\n")}</pre></div>
        </div>
      )}
    </>
  );
}
