import { useEffect, useState, useCallback } from "react";
import { api } from "../api";
import { useMetricsSocket } from "../ws";
import { useStore } from "../store";
import { PageHeader, StatCard, Spinner, JsonBlock } from "../components/UI";

function MiniChart({ data, label, color = "var(--accent)", height = 60 }) {
  if (!data || data.length < 2) return <div className="empty" style={{ padding: 8 }}><p>Collecting data...</p></div>;
  const values = data.map((d) => d.value);
  const max = Math.max(...values) || 1;
  const min = Math.min(...values);
  const w = 100 / values.length;
  return (
    <div style={{ position: "relative", height }}>
      <svg viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" style={{ width: "100%", height: "100%" }}>
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

export default function Benchmarks() {
  const { toast } = useStore();
  const { metrics: live, connected } = useMetricsSocket();
  const [benchmarks, setBenchmarks] = useState(null);
  const [sysHistory, setSysHistory] = useState({ memory: [], cpu: [], containers: [] });
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [b, memH, cpuH, cntH] = await Promise.all([
        api.getBenchmarks(),
        api.getMetricsHistory({ metric_type: "system", metric_name: "memory_used_percent", limit: 100 }).catch(() => ({ data: { metrics: [] } })),
        api.getMetricsHistory({ metric_type: "system", metric_name: "cpu_load_1m", limit: 100 }).catch(() => ({ data: { metrics: [] } })),
        api.getMetricsHistory({ metric_type: "system", metric_name: "containers_running", limit: 100 }).catch(() => ({ data: { metrics: [] } })),
      ]);
      setBenchmarks(b.data);
      setSysHistory({
        memory: (memH.data?.metrics || []).reverse(),
        cpu: (cpuH.data?.metrics || []).reverse(),
        containers: (cntH.data?.metrics || []).reverse(),
      });
    } catch (e) { toast(e.message, "error"); }
    finally { setLoading(false); }
  }, [toast]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { const t = setInterval(load, 30000); return () => clearInterval(t); }, [load]);

  if (loading && !benchmarks) return <Spinner />;

  const dep = benchmarks?.deployment || {};
  const dt = dep.deploy_time_seconds || {};
  const lat = benchmarks?.api_latency_ms?.deploy_endpoint || {};
  const sim = benchmarks?.simulations || {};

  const sys = live?.system || {};

  return (
    <>
      <PageHeader title="Performance Benchmarks" subtitle="Deployment metrics, latency percentiles, and system resources">
        <div className="btn-group">
          {connected && <span className="live-dot" title="Live" />}
          <button className="btn btn-secondary" onClick={load}>Refresh</button>
        </div>
      </PageHeader>

      <div className="section">
        <div className="section-title">Deployment Performance</div>
        <div className="stats-grid">
          <StatCard label="Total Deployments" value={dep.total_deploys ?? 0} color="blue" />
          <StatCard label="Success Rate" value={`${dep.success_rate_percent ?? 0}%`} color={dep.success_rate_percent >= 90 ? "green" : "orange"} />
          <StatCard label="Avg Deploy Time" value={`${dt.avg ?? 0}s`} meta={`P50: ${dt.p50 ?? 0}s`} />
          <StatCard label="P90 Deploy Time" value={`${dt.p90 ?? 0}s`} color={dt.p90 > 300 ? "red" : "green"} meta={`P99: ${dt.p99 ?? 0}s`} />
        </div>
      </div>

      <div className="section">
        <div className="section-title">API Latency (Deploy Endpoint)</div>
        <div className="stats-grid">
          <StatCard label="Avg Latency" value={`${lat.avg ?? 0}ms`} />
          <StatCard label="P50" value={`${lat.p50 ?? 0}ms`} />
          <StatCard label="P90" value={`${lat.p90 ?? 0}ms`} color={lat.p90 > 5000 ? "orange" : undefined} />
          <StatCard label="P99" value={`${lat.p99 ?? 0}ms`} color={lat.p99 > 10000 ? "red" : undefined} />
        </div>
      </div>

      <div className="section">
        <div className="section-title">Simulation Throughput</div>
        <div className="stats-grid">
          <StatCard label="Total Events" value={(sim.total_events_generated ?? 0).toLocaleString()} color="cyan" />
          <StatCard label="Completed Sims" value={sim.completed ?? 0} color="green" />
          <StatCard label="Failed Sims" value={sim.failed ?? 0} color={sim.failed > 0 ? "red" : undefined} />
          <StatCard label="Current EPS Target" value={live?.current_eps_target ?? 0} meta="Active simulations" />
        </div>
      </div>

      <div className="section">
        <div className="section-title">Live System Resources</div>
        <div className="stats-grid">
          <StatCard label="Memory Used" value={`${sys.memory_used_percent ?? 0}%`} color={sys.memory_used_percent > 85 ? "red" : sys.memory_used_percent > 70 ? "orange" : "green"} meta={`${sys.memory_available_mb ?? 0} MB free`} />
          <StatCard label="Disk Used" value={`${sys.disk_used_percent ?? 0}%`} color={sys.disk_used_percent > 90 ? "red" : undefined} />
          <StatCard label="CPU Load (1m)" value={sys.load_average?.[0]?.toFixed(2) ?? "—"} meta={`${sys.cpu_count ?? "?"} cores`} />
          <StatCard label="Containers Running" value={live?.by_status?.running ?? 0} color="green" meta={`${live?.total_agents ?? 0} total`} />
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16 }}>
        <div className="card">
          <div className="section-title">Memory % (history)</div>
          <MiniChart data={sysHistory.memory} label="Mem%" color="var(--orange)" />
        </div>
        <div className="card">
          <div className="section-title">CPU Load 1m (history)</div>
          <MiniChart data={sysHistory.cpu} label="Load" color="var(--cyan)" />
        </div>
        <div className="card">
          <div className="section-title">Running Containers (history)</div>
          <MiniChart data={sysHistory.containers} label="Running" color="var(--green)" />
        </div>
      </div>

      {benchmarks && (
        <div className="section" style={{ marginTop: 20 }}>
          <div className="section-title">Raw Benchmark Data</div>
          <JsonBlock data={benchmarks} />
        </div>
      )}
    </>
  );
}
