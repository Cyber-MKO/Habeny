import { useEffect, useState, useCallback } from "react";
import { api } from "../api";
import { useStore } from "../store";
import { PageHeader, StatCard, Pill, Spinner, JsonBlock, DataTable, Modal } from "../components/UI";

function VerdictBadge({ verdict }) {
  const color = verdict === "PASS" ? "var(--green)" : verdict === "FAIL" ? "var(--red)" : "var(--orange)";
  return <span style={{ fontWeight: 700, color, fontSize: 16 }}>{verdict}</span>;
}

function MiniChart({ data, color = "var(--accent)", height = 50 }) {
  if (!data || data.length < 2) return null;
  const max = Math.max(...data) || 1;
  const min = Math.min(...data);
  const w = 100 / data.length;
  return (
    <svg viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" style={{ width: "100%", height }}>
      <polyline fill="none" stroke={color} strokeWidth="1.5"
        points={data.map((v, i) => `${i * w + w / 2},${height - ((v - min) / (max - min || 1)) * (height - 4) - 2}`).join(" ")} />
    </svg>
  );
}

export default function BenchmarkRunner() {
  const { toast } = useStore();
  const [tab, setTab] = useState("launch");
  const [scenarios, setScenarios] = useState([]);
  const [benchmarks, setBenchmarks] = useState([]);
  const [loading, setLoading] = useState(true);

  const [selScenario, setSelScenario] = useState("linear_scale");
  const [launchConfig, setLaunchConfig] = useState({ name: "", siem_type: "none", siem_ip: "", siem_version: "", siem_auth_key: "", base_name: "bm", memory_limit: "256MB" });
  const [launching, setLaunching] = useState(false);

  const [managers, setManagers] = useState([]);

  const [detail, setDetail] = useState(null);
  const [detailMetrics, setDetailMetrics] = useState([]);
  const [detailBottlenecks, setDetailBottlenecks] = useState([]);
  const [liveData, setLiveData] = useState(null);

  const [compareIds, setCompareIds] = useState([]);
  const [comparison, setComparison] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [s, b, m] = await Promise.all([
        api.getBenchmarkScenarios().catch(() => ({ data: { scenarios: [] } })),
        api.listBenchmarks().catch(() => ({ data: { benchmarks: [] } })),
        api.getManagers().catch(() => ({ data: { managers: [] } })),
      ]);
      setScenarios(s.data?.scenarios || []);
      setBenchmarks(b.data?.benchmarks || []);
      setManagers(m.data?.managers || []);
    } catch (e) { toast(e.message, "error"); }
    finally { setLoading(false); }
  }, [toast]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    const hasRunning = benchmarks.some((b) => b.status === "running");
    if (!hasRunning) return;
    const t = setInterval(load, 10000);
    return () => clearInterval(t);
  }, [benchmarks, load]);

  useEffect(() => {
    if (!detail || detail.status !== "running") return;
    const t = setInterval(async () => {
      try {
        const res = await api.getBenchmark(detail.benchmark_id);
        setDetail(res.data);
        setLiveData(res.data?.live);
      } catch {}
    }, 5000);
    return () => clearInterval(t);
  }, [detail?.benchmark_id, detail?.status]);

  const handleLaunch = async () => {
    setLaunching(true);
    try {
      const payload = {
        scenario_id: selScenario,
        name: launchConfig.name || undefined,
        siem_type: launchConfig.siem_type,
        base_name: launchConfig.base_name,
        memory_limit: launchConfig.memory_limit,
      };
      if (launchConfig.siem_type !== "none") {
        payload.siem_ip = launchConfig.siem_ip || undefined;
        if (launchConfig.siem_version) payload.siem_version = launchConfig.siem_version;
        if (launchConfig.siem_auth_key) payload.siem_auth_key = launchConfig.siem_auth_key;
      }
      const res = await api.startBenchmark(payload);
      toast(res.message, "success");
      load();
      setTab("list");
    } catch (e) { toast(e.message, "error"); }
    finally { setLaunching(false); }
  };

  const handleStop = async (id) => {
    try { await api.stopBenchmark(id); toast("Stop requested", "success"); load(); }
    catch (e) { toast(e.message, "error"); }
  };

  const openDetail = async (bm) => {
    try {
      const [d, m, b] = await Promise.all([
        api.getBenchmark(bm.benchmark_id),
        api.getBenchmarkMetrics(bm.benchmark_id, { limit: 500 }).catch(() => ({ data: { metrics: [] } })),
        api.getBenchmarkBottlenecks(bm.benchmark_id).catch(() => ({ data: { bottlenecks: [] } })),
      ]);
      setDetail(d.data);
      setDetailMetrics(m.data?.metrics || []);
      setDetailBottlenecks(b.data?.bottlenecks || []);
      setLiveData(d.data?.live);
      setTab("detail");
    } catch (e) { toast(e.message, "error"); }
  };

  const toggleCompare = (id) => {
    setCompareIds((prev) => prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]);
  };

  const runCompare = async () => {
    if (compareIds.length < 2) return toast("Select at least 2 benchmarks", "error");
    try {
      const res = await api.compareBenchmarks(compareIds);
      setComparison(res.data);
      setTab("compare");
    } catch (e) { toast(e.message, "error"); }
  };

  const set = (k, v) => setLaunchConfig((p) => ({ ...p, [k]: v }));
  const summary = detail?.results?.summary || {};
  const phases = detail?.results?.phases || [];

  return (
    <>
      <PageHeader title="Benchmark Runner" subtitle="Multi-phase performance benchmarking">
        <div className="btn-group">
          {["launch", "list", "detail", "compare"].map((t) => (
            <button key={t} className={`btn btn-sm ${tab === t ? "btn-primary" : "btn-secondary"}`} onClick={() => setTab(t)}>
              {t === "launch" ? "Launch" : t === "list" ? "History" : t === "detail" ? "Results" : "Compare"}
            </button>
          ))}
        </div>
      </PageHeader>

      {tab === "launch" && (
        <>
          <div className="card" style={{ marginBottom: 16 }}>
            <div className="section-title">Select Scenario</div>
            <div className="stats-grid">
              {scenarios.map((s) => (
                <div key={s.id} className={`card stat-card${selScenario === s.id ? " active" : ""}`}
                     style={{ cursor: "pointer", border: selScenario === s.id ? "2px solid var(--accent)" : undefined }}
                     onClick={() => setSelScenario(s.id)}>
                  <div className="stat-label">{s.name}</div>
                  <div className="stat-meta">{s.description}</div>
                  <div className="stat-meta" style={{ marginTop: 4 }}>{s.phases} phases · {s.total_agents} total agents</div>
                </div>
              ))}
            </div>
          </div>
          <div className="card" style={{ marginBottom: 16 }}>
            <div className="section-title">Configuration</div>
            <div className="form-grid">
              <div className="field" style={{ gridColumn: "1 / -1" }}>
                <label>Manager Profile</label>
                <select className="select" onChange={(e) => {
                  const mgr = managers.find((m) => m.manager_id === e.target.value);
                  if (!mgr) return;
                  setLaunchConfig((p) => ({
                    ...p,
                    siem_type: mgr.siem_type || p.siem_type,
                    siem_ip: mgr.siem_ip || "",
                    siem_version: mgr.siem_version || "",
                    siem_auth_key: mgr.siem_auth_key || "",
                  }));
                }}>
                  <option value="">— Manual configuration —</option>
                  {managers.map((m) => <option key={m.manager_id} value={m.manager_id}>{m.name} ({m.siem_type} — {m.siem_ip || "no IP"})</option>)}
                </select>
              </div>
              <div className="field"><label>Benchmark Name</label><input className="input" value={launchConfig.name} onChange={(e) => set("name", e.target.value)} placeholder="Optional" /></div>
              <div className="field"><label>SIEM Type</label>
                <select className="select" value={launchConfig.siem_type} onChange={(e) => set("siem_type", e.target.value)}>
                  <option value="none">None (bare)</option><option value="wazuh">Wazuh</option><option value="ossec">OSSEC</option><option value="utmstack">UTMstack</option><option value="elastic">Elastic</option>
                </select>
              </div>
              {launchConfig.siem_type !== "none" && (
                <div className="field"><label>Manager IP / Hostname</label><input className="input" value={launchConfig.siem_ip} onChange={(e) => set("siem_ip", e.target.value)} placeholder="192.168.1.100" /></div>
              )}
              {launchConfig.siem_type !== "none" && launchConfig.siem_type !== "utmstack" && (
                <div className="field"><label>{launchConfig.siem_type === "elastic" ? "Agent Version" : "SIEM Version"}</label><input className="input" value={launchConfig.siem_version} onChange={(e) => set("siem_version", e.target.value)} placeholder={launchConfig.siem_type === "elastic" ? "9.0.2" : "4.14.2"} /></div>
              )}
              {(launchConfig.siem_type === "utmstack" || launchConfig.siem_type === "elastic") && (
                <div className="field"><label>{launchConfig.siem_type === "elastic" ? "Fleet Enrollment Token" : "UTMstack Auth Key"}</label><input className="input" value={launchConfig.siem_auth_key} onChange={(e) => set("siem_auth_key", e.target.value)} /></div>
              )}
              <div className="field"><label>Base Name</label><input className="input" value={launchConfig.base_name} onChange={(e) => set("base_name", e.target.value)} /></div>
              <div className="field"><label>Memory per Container</label><input className="input" value={launchConfig.memory_limit} onChange={(e) => set("memory_limit", e.target.value)} /></div>
            </div>
          </div>
          <button className="btn btn-primary" onClick={handleLaunch} disabled={launching}>
            {launching ? "Starting..." : `Launch "${scenarios.find((s) => s.id === selScenario)?.name || selScenario}"`}
          </button>
        </>
      )}

      {tab === "list" && (
        <>
          <div className="btn-group" style={{ marginBottom: 12 }}>
            <button className="btn btn-secondary" onClick={load}>Refresh</button>
            <button className="btn btn-primary" onClick={runCompare} disabled={compareIds.length < 2}>Compare Selected ({compareIds.length})</button>
          </div>
          <div className="card">
            <DataTable
              columns={[
                { key: "sel", label: "", render: (r) => <input type="checkbox" checked={compareIds.includes(r.benchmark_id)} onChange={() => toggleCompare(r.benchmark_id)} /> },
                { key: "name", label: "Name", render: (r) => r.name || r.benchmark_id.slice(0, 8) },
                { key: "scenario_id", label: "Scenario" },
                { key: "siem_type", label: "SIEM", render: (r) => <Pill status={r.siem_type === "none" ? "unknown" : (r.siem_type || "none")} /> },
                { key: "status", label: "Status", render: (r) => <Pill status={r.status} /> },
                { key: "current_phase", label: "Phase" },
                { key: "started_at", label: "Started", render: (r) => r.started_at ? new Date(r.started_at).toLocaleString() : "—" },
                { key: "actions", label: "", render: (r) => (
                  <div className="btn-group">
                    <button className="btn btn-sm btn-secondary" onClick={() => openDetail(r)}>Details</button>
                    {r.status === "running" && <button className="btn btn-sm btn-danger" onClick={() => handleStop(r.benchmark_id)}>Stop</button>}
                  </div>
                )},
              ]}
              rows={benchmarks}
              emptyMsg="No benchmarks yet. Launch one from the Launch tab."
            />
          </div>
        </>
      )}

      {tab === "detail" && detail && (
        <>
          <div className="stats-grid">
            <StatCard label="Verdict" value={<VerdictBadge verdict={summary.verdict || "—"} />} />
            <StatCard label="Scenario" value={detail?.scenario_id?.replace(/_/g, " ") || "—"} />
            <StatCard label="SIEM Type" value={(detail?.siem_type || "none").toUpperCase()} color="cyan" />
            <StatCard label="Max Stable Agents" value={summary.max_stable_agents ?? "—"} color="blue" />
            <StatCard label="Success Rate" value={`${summary.success_rate_percent ?? 0}%`} color={summary.success_rate_percent >= 90 ? "green" : "orange"} />
            <StatCard label="Avg Deploy Time" value={`${summary.avg_deploy_time_seconds ?? 0}s`} />
            <StatCard label="Phases" value={`${summary.phases_completed ?? 0}/${summary.phases_total ?? 0}`} />
            <StatCard label="Bottlenecks" value={summary.bottlenecks_total ?? 0} color={summary.bottlenecks_critical > 0 ? "red" : "green"} />
          </div>

          {liveData && detail.status === "running" && (
            <div className="card" style={{ marginBottom: 16 }}>
              <div className="section-title">Live — Phase {liveData.phase}: {liveData.label}</div>
              <div className="stats-grid">
                <StatCard label="Elapsed" value={`${Math.round(liveData.elapsed || 0)}s`} />
                <StatCard label="Memory" value={`${(liveData.metrics?.system_memory_percent || 0).toFixed(1)}%`} color={liveData.metrics?.system_memory_percent > 85 ? "red" : "green"} />
                <StatCard label="CPU Load" value={(liveData.metrics?.system_load_1m || 0).toFixed(2)} />
                <StatCard label="Containers Running" value={liveData.metrics?.containers_running ?? 0} color="cyan" />
              </div>
            </div>
          )}

          {phases.length > 0 && (
            <div className="card" style={{ marginBottom: 16 }}>
              <div className="section-title">Phase Results</div>
              <DataTable
                columns={[
                  { key: "label", label: "Phase" },
                  { key: "status", label: "Status", render: (r) => <Pill status={r.status} /> },
                  { key: "deploy_total", label: "Deployed" },
                  { key: "deploy_success", label: "Success" },
                  { key: "deploy_failures", label: "Failed", render: (r) => <span style={{ color: r.deploy_failures > 0 ? "var(--red)" : "inherit" }}>{r.deploy_failures}</span> },
                  { key: "deploy_rate_per_min", label: "Rate/min", render: (r) => (r.deploy_rate_per_min || 0).toFixed(1) },
                  { key: "deploy_time_p90", label: "P90 (s)", render: (r) => (r.deploy_time_p90 || 0).toFixed(1) },
                ]}
                rows={phases}
              />
            </div>
          )}

          {detailBottlenecks.length > 0 && (
            <div className="card" style={{ marginBottom: 16 }}>
              <div className="section-title">Bottlenecks Detected</div>
              <DataTable
                columns={[
                  { key: "severity", label: "Severity", render: (r) => <Pill status={r.severity} /> },
                  { key: "component", label: "Component" },
                  { key: "title", label: "Issue" },
                  { key: "actual_value", label: "Value", render: (r) => `${(r.actual_value || 0).toFixed(1)} (threshold: ${r.threshold})` },
                  { key: "occurrences", label: "Count" },
                  { key: "recommendation", label: "Recommendation" },
                ]}
                rows={detailBottlenecks}
              />
            </div>
          )}

          {detailMetrics.length > 0 && (
            <div className="card">
              <div className="section-title">Metrics Trend ({detailMetrics.length} samples)</div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
                {["system_memory_percent", "system_load_1m", "containers_running", "system_disk_percent"].map((name) => {
                  const vals = detailMetrics.filter((m) => m.metric_name === name).reverse().map((m) => m.value);
                  return vals.length > 1 ? (
                    <div key={name}>
                      <div style={{ fontSize: 11, color: "var(--text-dim)", marginBottom: 4 }}>{name}: {vals[vals.length - 1]?.toFixed(1)}</div>
                      <MiniChart data={vals} color={name.includes("memory") ? "var(--orange)" : name.includes("load") ? "var(--cyan)" : "var(--green)"} />
                    </div>
                  ) : null;
                })}
              </div>
            </div>
          )}
        </>
      )}

      {tab === "compare" && comparison && (
        <>
          {comparison.summary && (
            <div className="card" style={{ marginBottom: 16 }}>
              <div className="section-title">Summary</div>
              <p style={{ fontSize: 14 }}>{comparison.summary}</p>
            </div>
          )}

          <div className="card" style={{ marginBottom: 16 }}>
            <div className="section-title">Side-by-Side</div>
            <DataTable
              columns={[
                { key: "name", label: "Benchmark", render: (r) => <>{r.name || r.benchmark_id.slice(0, 8)} {r.benchmark_id === comparison.winner ? <span style={{ color: "var(--green)", fontSize: 11 }}> WINNER</span> : ""}</> },
                { key: "scenario_id", label: "Scenario" },
                { key: "siem_type", label: "SIEM", render: (r) => r.siem_type || "none" },
                { key: "verdict", label: "Verdict", render: (r) => <VerdictBadge verdict={r.verdict} /> },
                { key: "max_agents", label: "Max Agents" },
                { key: "success_rate", label: "Success %", render: (r) => `${r.success_rate}%` },
                { key: "avg_deploy_time", label: "Avg Deploy (s)", render: (r) => r.avg_deploy_time.toFixed(1) },
                { key: "bottlenecks", label: "Bottlenecks" },
              ]}
              rows={comparison.benchmarks}
            />
          </div>

          {(comparison.improvements?.length > 0 || comparison.regressions?.length > 0) && (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
              <div className="card">
                <div className="section-title" style={{ color: "var(--green)" }}>Improvements</div>
                {comparison.improvements?.length ? comparison.improvements.map((m, i) => (
                  <div key={i} style={{ padding: "4px 0", fontSize: 13 }}>
                    <strong>{m.metric}</strong>: {m.baseline} → {m.current} ({m.percent_change}% better)
                  </div>
                )) : <p style={{ color: "var(--text-muted)", fontSize: 13 }}>None</p>}
              </div>
              <div className="card">
                <div className="section-title" style={{ color: "var(--red)" }}>Regressions</div>
                {comparison.regressions?.length ? comparison.regressions.map((m, i) => (
                  <div key={i} style={{ padding: "4px 0", fontSize: 13 }}>
                    <strong>{m.metric}</strong>: {m.baseline} → {m.current} ({m.percent_change}% worse)
                  </div>
                )) : <p style={{ color: "var(--text-muted)", fontSize: 13 }}>None</p>}
              </div>
            </div>
          )}
        </>
      )}
    </>
  );
}
