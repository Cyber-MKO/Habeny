import { useEffect, useState, useCallback } from "react";
import { api } from "../api";
import { useStore } from "../store";
import { PageHeader, StatCard, Pill, Spinner, DataTable } from "../components/UI";
import { formatDateTime, t } from "../i18n";

function VerdictBadge({ verdict }) {
  const color = verdict === "PASS" ? "var(--green)" : verdict === "FAIL" ? "var(--red)" : "var(--orange)";
  return <span style={{ fontWeight: 700, color, fontSize: 16 }}>{verdict}</span>;
}

function MiniChart({ data, label = "", color = "var(--accent)", height = 50 }) {
  if (!data || data.length < 2) return null;
  const max = Math.max(...data) || 1;
  const min = Math.min(...data);
  const w = 100 / data.length;
  return (
    <svg viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" style={{ width: "100%", height }} role="img"
      aria-label={t("{label}: latest {latest}, lowest {min}, highest {max}", { label, latest: Number(data[data.length - 1]).toFixed(1), min: min.toFixed(1), max: max.toFixed(1) })}>
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
  const [launchConfig, setLaunchConfig] = useState({ name: "", siem_type: "none", siem_ip: "", siem_version: "", siem_auth_key: "", base_name: "bm", memory_limit: "256MB", manager_profile_id: "" });
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
    const timer = setInterval(load, 10000);
    return () => clearInterval(timer);
  }, [benchmarks, load]);

  const detailId = detail?.benchmark_id;
  const detailRunning = detail?.status === "running";
  useEffect(() => {
    if (!detailId || !detailRunning) return;
    const timer = setInterval(async () => {
      try {
        const res = await api.getBenchmark(detailId);
        setDetail(res.data);
        setLiveData(res.data?.live);
      } catch { /* keep showing the last update; the next poll retries */ }
    }, 5000);
    return () => clearInterval(timer);
  }, [detailId, detailRunning]);

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
      if (launchConfig.manager_profile_id) payload.manager_profile_id = launchConfig.manager_profile_id;
      const res = await api.startBenchmark(payload);
      toast(res.message, "success");
      load();
      setTab("list");
    } catch (e) { toast(e.message, "error"); }
    finally { setLaunching(false); }
  };

  const handleStop = async (id) => {
    try { await api.stopBenchmark(id); toast(t("Stop requested"), "success"); load(); }
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
    if (compareIds.length < 2) return toast(t("Select at least 2 benchmarks"), "error");
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
      <PageHeader title={t("Benchmark Runner")} subtitle={t("Multi-phase performance benchmarking")}>
        <div className="btn-group">
          {["launch", "list", "detail", "compare"].map((name) => (
            <button key={name} className={`btn btn-sm ${tab === name ? "btn-primary" : "btn-secondary"}`} onClick={() => setTab(name)}>
              {name === "launch" ? t("Launch") : name === "list" ? t("History") : name === "detail" ? t("Results") : t("Compare")}
            </button>
          ))}
        </div>
      </PageHeader>

      {tab === "launch" && (
        <>
          <div className="card" style={{ marginBottom: 16 }}>
            <div className="section-title">{t("Select Scenario")}</div>
            <div className="stats-grid">
              {scenarios.map((s) => (
                <div key={s.id} className={`card stat-card${selScenario === s.id ? " active" : ""}`}
                     style={{ cursor: "pointer", border: selScenario === s.id ? "2px solid var(--accent)" : undefined }}
                     onClick={() => setSelScenario(s.id)}>
                  <div className="stat-label">{s.name}</div>
                  <div className="stat-meta">{s.description}</div>
                  <div className="stat-meta" style={{ marginTop: 4 }}>{s.phases} {t("phases ·")} {s.total_agents} {t("total agents")}</div>
                </div>
              ))}
            </div>
          </div>
          <div className="card" style={{ marginBottom: 16 }}>
            <div className="section-title">{t("Configuration")}</div>
            <div className="form-grid">
              <div className="field" style={{ gridColumn: "1 / -1" }}>
                <label htmlFor="benchmark-runner-manager-profile">{t("Manager Profile")}</label>
                <select id="benchmark-runner-manager-profile" className="select" onChange={(e) => {
                  const mgr = managers.find((m) => m.manager_id === e.target.value);
                  if (!mgr) { setLaunchConfig((p) => ({ ...p, manager_profile_id: "" })); return; }
                  setLaunchConfig((p) => ({
                    ...p,
                    manager_profile_id: mgr.manager_id,
                    siem_type: mgr.siem_type || p.siem_type,
                    siem_ip: mgr.siem_ip || "",
                    siem_version: mgr.siem_version || "",
                    siem_auth_key: "", // stored encrypted in the profile; the server fills it in
                  }));
                }}>
                  <option value="">{t("— Manual configuration —")}</option>
                  {managers.map((m) => <option key={m.manager_id} value={m.manager_id}>{m.name} ({m.siem_type} — {m.siem_ip || t("no IP")})</option>)}
                </select>
              </div>
              <div className="field"><label htmlFor="benchmark-runner-benchmark-name">{t("Benchmark Name")}</label><input id="benchmark-runner-benchmark-name" className="input" value={launchConfig.name} onChange={(e) => set("name", e.target.value)} placeholder={t("Optional")} /></div>
              <div className="field"><label htmlFor="benchmark-runner-siem-type">{t("SIEM Type")}</label>
                <select id="benchmark-runner-siem-type" className="select" value={launchConfig.siem_type} onChange={(e) => set("siem_type", e.target.value)}>
                  <option value="none">{t("None (bare)")}</option><option value="wazuh">Wazuh</option><option value="ossec">OSSEC</option><option value="utmstack">UTMstack</option><option value="elastic">Elastic</option>
                </select>
              </div>
              {launchConfig.siem_type !== "none" && (
                <div className="field"><label htmlFor="benchmark-runner-manager-ip-hostname">{t("Manager IP / Hostname")}</label><input id="benchmark-runner-manager-ip-hostname" className="input" value={launchConfig.siem_ip} onChange={(e) => set("siem_ip", e.target.value)} placeholder="192.168.1.100" /></div>
              )}
              {launchConfig.siem_type !== "none" && launchConfig.siem_type !== "utmstack" && (
                <div className="field"><label>{launchConfig.siem_type === "elastic" ? t("Agent Version") : t("SIEM Version")}</label><input className="input" value={launchConfig.siem_version} onChange={(e) => set("siem_version", e.target.value)} placeholder={launchConfig.siem_type === "elastic" ? "9.0.2" : "4.14.2"} /></div>
              )}
              {(launchConfig.siem_type === "utmstack" || launchConfig.siem_type === "elastic") && (
                <div className="field"><label>{launchConfig.siem_type === "elastic" ? t("Fleet Enrollment Token") : t("UTMstack Auth Key")}</label><input className="input" value={launchConfig.siem_auth_key} onChange={(e) => set("siem_auth_key", e.target.value)}
                  placeholder={(() => { const m = managers.find((x) => x.manager_id === launchConfig.manager_profile_id); return m?.has_siem_auth_key ? t("From profile ({hint}) — type to override", { hint: m.siem_auth_key_hint }) : ""; })()} /></div>
              )}
              <div className="field"><label htmlFor="benchmark-runner-base-name">{t("Base Name")}</label><input id="benchmark-runner-base-name" className="input" value={launchConfig.base_name} onChange={(e) => set("base_name", e.target.value)} /></div>
              <div className="field"><label htmlFor="benchmark-runner-memory-per-container">{t("Memory per Container")}</label><input id="benchmark-runner-memory-per-container" className="input" value={launchConfig.memory_limit} onChange={(e) => set("memory_limit", e.target.value)} /></div>
            </div>
          </div>
          <button className="btn btn-primary" onClick={handleLaunch} disabled={launching}>
            {launching ? t("Starting...") : t("Launch \"{scenario}\"", { scenario: scenarios.find((s) => s.id === selScenario)?.name || selScenario })}
          </button>
        </>
      )}

      {tab === "list" && (
        <>
          <div className="btn-group" style={{ marginBottom: 12 }}>
            <button className="btn btn-secondary" onClick={load}>{t("Refresh")}</button>
            <button className="btn btn-primary" onClick={runCompare} disabled={compareIds.length < 2}>{t("Compare Selected (")}{compareIds.length})</button>
          </div>
          <div className="card">
            {loading && !benchmarks.length ? <Spinner /> : <DataTable
              columns={[
                { key: "sel", label: "", render: (r) => <input type="checkbox" checked={compareIds.includes(r.benchmark_id)} onChange={() => toggleCompare(r.benchmark_id)} /> },
                { key: "name", label: t("Name"), render: (r) => r.name || r.benchmark_id.slice(0, 8) },
                { key: "scenario_id", label: t("Scenario") },
                { key: "siem_type", label: "SIEM", render: (r) => <Pill status={r.siem_type === "none" ? "unknown" : (r.siem_type || "none")} /> },
                { key: "status", label: t("Status"), render: (r) => <Pill status={r.status} /> },
                { key: "current_phase", label: t("Phase") },
                { key: "started_at", label: t("Started"), render: (r) => r.started_at ? formatDateTime(r.started_at) : "—" },
                { key: "actions", label: "", render: (r) => (
                  <div className="btn-group">
                    <button className="btn btn-sm btn-secondary" onClick={() => openDetail(r)}>{t("Details")}</button>
                    {r.status === "running" && <button className="btn btn-sm btn-danger" onClick={() => handleStop(r.benchmark_id)}>{t("Stop")}</button>}
                  </div>
                )},
              ]}
              rows={benchmarks}
              emptyMsg={t("No benchmarks yet. Launch one from the Launch tab.")}
            />}
          </div>
        </>
      )}

      {tab === "detail" && detail && (
        <>
          <div className="stats-grid">
            <StatCard label={t("Verdict")} value={<VerdictBadge verdict={summary.verdict || "—"} />} />
            <StatCard label={t("Scenario")} value={detail?.scenario_id?.replace(/_/g, " ") || "—"} />
            <StatCard label={t("SIEM Type")} value={(detail?.siem_type || "none").toUpperCase()} color="cyan" />
            <StatCard label={t("Max Stable Agents")} value={summary.max_stable_agents ?? "—"} color="blue" />
            <StatCard label={t("Success Rate")} value={`${summary.success_rate_percent ?? 0}%`} color={summary.success_rate_percent >= 90 ? "green" : "orange"} />
            <StatCard label={t("Avg Deploy Time")} value={`${summary.avg_deploy_time_seconds ?? 0}s`} />
            <StatCard label={t("Phases")} value={`${summary.phases_completed ?? 0}/${summary.phases_total ?? 0}`} />
            <StatCard label={t("Bottlenecks")} value={summary.bottlenecks_total ?? 0} color={summary.bottlenecks_critical > 0 ? "red" : "green"} />
          </div>

          {liveData && detail.status === "running" && (
            <div className="card" style={{ marginBottom: 16 }}>
              <div className="section-title">{t("Live — Phase")} {liveData.phase}: {liveData.label}</div>
              <div className="stats-grid">
                <StatCard label={t("Elapsed")} value={`${Math.round(liveData.elapsed || 0)}s`} />
                <StatCard label={t("Memory")} value={`${(liveData.metrics?.system_memory_percent || 0).toFixed(1)}%`} color={liveData.metrics?.system_memory_percent > 85 ? "red" : "green"} />
                <StatCard label={t("CPU Load")} value={(liveData.metrics?.system_load_1m || 0).toFixed(2)} />
                <StatCard label={t("Containers Running")} value={liveData.metrics?.containers_running ?? 0} color="cyan" />
              </div>
            </div>
          )}

          {phases.length > 0 && (
            <div className="card" style={{ marginBottom: 16 }}>
              <div className="section-title">{t("Phase Results")}</div>
              <DataTable
                columns={[
                  { key: "label", label: t("Phase") },
                  { key: "status", label: t("Status"), render: (r) => <Pill status={r.status} /> },
                  { key: "deploy_total", label: t("Deployed") },
                  { key: "deploy_success", label: t("Success") },
                  { key: "deploy_failures", label: t("Failed"), render: (r) => <span style={{ color: r.deploy_failures > 0 ? "var(--red)" : "inherit" }}>{r.deploy_failures}</span> },
                  { key: "deploy_rate_per_min", label: t("Rate/min"), render: (r) => (r.deploy_rate_per_min || 0).toFixed(1) },
                  { key: "deploy_time_p90", label: t("P90 (s)"), render: (r) => (r.deploy_time_p90 || 0).toFixed(1) },
                ]}
                rows={phases}
              />
            </div>
          )}

          {detailBottlenecks.length > 0 && (
            <div className="card" style={{ marginBottom: 16 }}>
              <div className="section-title">{t("Bottlenecks Detected")}</div>
              <DataTable
                columns={[
                  { key: "severity", label: t("Severity"), render: (r) => <Pill status={r.severity} /> },
                  { key: "component", label: t("Component") },
                  { key: "title", label: t("Issue") },
                  { key: "actual_value", label: t("Value"), render: (r) => `${(r.actual_value || 0).toFixed(1)} (threshold: ${r.threshold})` },
                  { key: "occurrences", label: t("Count") },
                  { key: "recommendation", label: t("Recommendation") },
                ]}
                rows={detailBottlenecks}
              />
            </div>
          )}

          {detailMetrics.length > 0 && (
            <div className="card">
              <div className="section-title">{t("Metrics Trend (")}{detailMetrics.length} {t("samples)")}</div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
                {["system_memory_percent", "system_load_1m", "containers_running", "system_disk_percent"].map((name) => {
                  const vals = detailMetrics.filter((m) => m.metric_name === name).reverse().map((m) => m.value);
                  return vals.length > 1 ? (
                    <div key={name}>
                      <div style={{ fontSize: 11, color: "var(--text-dim)", marginBottom: 4 }}>{name}: {vals[vals.length - 1]?.toFixed(1)}</div>
                      <MiniChart data={vals} label={name} color={name.includes("memory") ? "var(--orange)" : name.includes("load") ? "var(--cyan)" : "var(--green)"} />
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
              <div className="section-title">{t("Summary")}</div>
              <p style={{ fontSize: 14 }}>{comparison.summary}</p>
            </div>
          )}

          <div className="card" style={{ marginBottom: 16 }}>
            <div className="section-title">{t("Side-by-Side")}</div>
            <DataTable
              columns={[
                { key: "name", label: t("Benchmark"), render: (r) => <>{r.name || r.benchmark_id.slice(0, 8)} {r.benchmark_id === comparison.winner ? <span style={{ color: "var(--green)", fontSize: 11 }}> WINNER</span> : ""}</> },
                { key: "scenario_id", label: t("Scenario") },
                { key: "siem_type", label: "SIEM", render: (r) => r.siem_type || "none" },
                { key: "verdict", label: t("Verdict"), render: (r) => <VerdictBadge verdict={r.verdict} /> },
                { key: "max_agents", label: t("Max Agents") },
                { key: "success_rate", label: t("Success %"), render: (r) => `${r.success_rate}%` },
                { key: "avg_deploy_time", label: t("Avg Deploy (s)"), render: (r) => r.avg_deploy_time.toFixed(1) },
                { key: "bottlenecks", label: t("Bottlenecks") },
              ]}
              rows={comparison.benchmarks}
            />
          </div>

          {(comparison.improvements?.length > 0 || comparison.regressions?.length > 0) && (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
              <div className="card">
                <div className="section-title" style={{ color: "var(--green)" }}>{t("Improvements")}</div>
                {comparison.improvements?.length ? comparison.improvements.map((m, i) => (
                  <div key={i} style={{ padding: "4px 0", fontSize: 13 }}>
                    <strong>{m.metric}</strong>: {m.baseline} → {m.current} ({m.percent_change}{t("% better)")}
                  </div>
                )) : <p style={{ color: "var(--text-muted)", fontSize: 13 }}>{t("None")}</p>}
              </div>
              <div className="card">
                <div className="section-title" style={{ color: "var(--red)" }}>{t("Regressions")}</div>
                {comparison.regressions?.length ? comparison.regressions.map((m, i) => (
                  <div key={i} style={{ padding: "4px 0", fontSize: 13 }}>
                    <strong>{m.metric}</strong>: {m.baseline} → {m.current} ({m.percent_change}{t("% worse)")}
                  </div>
                )) : <p style={{ color: "var(--text-muted)", fontSize: 13 }}>{t("None")}</p>}
              </div>
            </div>
          )}
        </>
      )}
    </>
  );
}
