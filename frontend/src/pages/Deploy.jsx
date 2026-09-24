import { useState, useEffect, useRef } from "react";
import { api } from "../api";
import { useStore } from "../store";
import { PageHeader, Pill, Spinner } from "../components/UI";
import { Details } from "../components/Details";

const DEFAULTS = {
  count: 2, siem_type: "none", siem_ip: "", siem_version: "4.14.2", siem_auth_key: "",
  os_type: "ubuntu_22_04", agent_group: "default", agent_base_name: "container",
  memory_limit: "512MB", cpu_shares: 1024, config_template_id: "",
  autostart: true, auto_create_group: true, parallel_mode: "multiprocessing",
  manager_profile_id: "",
};

const POLL_MS = 1000;

// crypto.randomUUID is unavailable on plain-http (non-localhost) origins
const newDeploymentId = () =>
  `dep-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;

const localEvent = (message, level = "info") => ({ timestamp: new Date().toISOString(), level, container: null, message });

const CONTAINER_LABEL = { pending: "queued", running: "deploying" };

function formatElapsed(fromIso, toIso) {
  const secs = Math.max(0, Math.round(((toIso ? new Date(toIso) : new Date()) - new Date(fromIso)) / 1000));
  return secs < 60 ? `${secs}s` : `${Math.floor(secs / 60)}m ${secs % 60}s`;
}

function DeployActivity({ progress, active }) {
  const logRef = useRef(null);
  const [, tick] = useState(0);

  // Keep the elapsed timer moving between polls
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, [active]);

  // Follow the newest activity line
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [progress.events.length]);

  const { total, completed, successful, failed, containers, events } = progress;
  const pct = total ? Math.round((completed / total) * 100) : 0;
  const inFlight = containers.filter((c) => c.status === "running").length;

  return (
    <div className="section deploy-activity" style={{ marginTop: 20 }}>
      <div className="section-title">Deployment Activity</div>
      <div className="card">
        <div className="deploy-activity-head">
          <Pill status={progress.status === "running" ? "deploying" : progress.status} />
          <span>{completed}/{total} finished</span>
          {inFlight > 0 && <span className="text-dim">{inFlight} in progress</span>}
          <span className="text-green">{successful} succeeded</span>
          {failed > 0 && <span className="text-red">{failed} failed</span>}
          <span className="text-dim" style={{ marginLeft: "auto" }}>
            {active && <Spinner />} {formatElapsed(progress.started_at, progress.finished_at)}
          </span>
        </div>
        <div className="deploy-progress-bar">
          <div className={`deploy-progress-fill${failed ? " has-failures" : ""}`} style={{ width: `${pct}%` }} />
        </div>

        <div className="deploy-log" ref={logRef}>
          {events.map((ev, i) => (
            <div key={i} className={`deploy-log-line level-${ev.level}`}>
              <span className="deploy-log-time">{new Date(ev.timestamp).toLocaleTimeString()}</span>
              {ev.container && <span className="deploy-log-container">{ev.container}</span>}
              <span>{ev.message}</span>
            </div>
          ))}
        </div>

        {containers.length > 0 && (
          <div className="table-wrap" style={{ marginTop: 16 }}>
            <table>
              <thead>
                <tr><th>Container</th><th>Status</th><th>Current step</th></tr>
              </thead>
              <tbody>
                {containers.map((c) => (
                  <tr key={c.name}>
                    <td className="mono">{c.name}</td>
                    <td><Pill status={CONTAINER_LABEL[c.status] || c.status} /></td>
                    <td className={c.status === "failed" ? "text-red" : "text-dim"}>{c.step}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

export default function Deploy() {
  const { toast } = useStore();
  const [form, setForm] = useState(DEFAULTS);
  const [result, setResult] = useState(null);
  const [deploying, setDeploying] = useState(false);
  const [managers, setManagers] = useState([]);
  const [progress, setProgress] = useState(null);
  const [deploymentId, setDeploymentId] = useState(null);

  // Poll the server-side progress feed while a deployment is in flight
  useEffect(() => {
    if (!deploying || !deploymentId) return;
    let cancelled = false;
    let timer;
    const poll = async () => {
      try {
        const res = await api.getDeployProgress(deploymentId);
        if (!cancelled && res.data) setProgress((prev) => mergeProgress(prev, res.data));
      } catch {
        // Not registered yet (request still in flight) — keep polling
      }
      if (!cancelled) timer = setTimeout(poll, POLL_MS);
    };
    poll();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [deploying, deploymentId]);

  useEffect(() => {
    api.getManagers().then((r) => setManagers(r.data?.managers || [])).catch(() => {});
  }, []);

  const set = (k, v) => setForm((p) => ({ ...p, [k]: v }));

  const applyManager = (managerId) => {
    set("manager_profile_id", managerId);
    if (!managerId) return;
    const mgr = managers.find((m) => m.manager_id === managerId);
    if (!mgr) return;
    setForm((p) => ({
      ...p,
      manager_profile_id: managerId,
      siem_type: mgr.siem_type || p.siem_type,
      siem_ip: mgr.siem_ip || "",
      siem_version: mgr.siem_version || "",
      siem_auth_key: "", // stored encrypted in the profile; the server fills it in
      os_type: mgr.os_type || p.os_type,
      agent_group: mgr.agent_group || p.agent_group,
      memory_limit: mgr.memory_limit || p.memory_limit,
      cpu_shares: mgr.cpu_shares || p.cpu_shares,
      config_template_id: mgr.config_template_id || "",
    }));
  };

  const selectedManager = managers.find((m) => m.manager_id === form.manager_profile_id);
  const isBare = form.siem_type === "none";
  const isUtm = form.siem_type === "utmstack";
  const isElastic = form.siem_type === "elastic";
  const needsAuthKey = isUtm || isElastic;

  const handleSubmit = async (e) => {
    e.preventDefault();
    const id = newDeploymentId();
    setResult(null);
    setDeploymentId(id);
    setProgress({
      deployment_id: id, status: "running", started_at: new Date().toISOString(), finished_at: null,
      total: Number(form.count), completed: 0, successful: 0, failed: 0, containers: [],
      events: [localEvent("Sending deployment request to the server…")],
      local: true,
    });
    setDeploying(true);
    try {
      const payload = {
        count: Number(form.count),
        siem_type: form.siem_type,
        os_type: form.os_type,
        agent_group: form.agent_group,
        agent_base_name: form.agent_base_name,
        memory_limit: form.memory_limit,
        cpu_shares: Number(form.cpu_shares),
        config_template_id: form.config_template_id || null,
        autostart: form.autostart,
        auto_create_group: form.auto_create_group,
        parallel_mode: form.parallel_mode,
        deployment_id: id,
      };
      if (form.manager_profile_id) payload.manager_profile_id = form.manager_profile_id;
      if (!isBare) {
        payload.siem_ip = form.siem_ip;
        if (!needsAuthKey || isElastic) payload.siem_version = form.siem_version;
        if (needsAuthKey) payload.siem_auth_key = form.siem_auth_key;
      }
      const res = await api.deploy(payload);
      setResult(res);
      // Pull the final state so the feed ends on the server's summary
      const final = await api.getDeployProgress(id).catch(() => null);
      setProgress((prev) => final?.data ? mergeProgress(prev, final.data) : finishLocal(prev, res.message, res.success));
      toast(res.message || "Deployment complete", res.success ? "success" : "error");
    } catch (err) {
      setResult({ error: err.message });
      setProgress((prev) => finishLocal(prev, `Deployment failed: ${err.message}`, false));
      toast(err.message, "error");
    } finally {
      setDeploying(false);
    }
  };

  return (
    <>
      <PageHeader title="Deploy Containers" subtitle="Create containers and install SIEM agents at scale" />

      <form onSubmit={handleSubmit}>
        <div className="card" style={{ marginBottom: 16 }}>
          <div className="form-grid">
            <div className="field" style={{ gridColumn: "1 / -1" }}>
              <label htmlFor="deploy-manager-profile">Manager Profile</label>
              <select id="deploy-manager-profile" className="select" value={form.manager_profile_id} onChange={(e) => applyManager(e.target.value)}>
                <option value="">— Manual configuration —</option>
                {managers.map((m) => <option key={m.manager_id} value={m.manager_id}>{m.name} ({m.siem_type} — {m.siem_ip || "no IP"})</option>)}
              </select>
            </div>
            <div className="field">
              <label htmlFor="deploy-container-count">Container Count</label>
              <input id="deploy-container-count" className="input" type="number" min={1} max={1000} value={form.count} onChange={(e) => set("count", e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="deploy-siem-type">SIEM Type</label>
              <select id="deploy-siem-type" className="select" value={form.siem_type} onChange={(e) => set("siem_type", e.target.value)}>
                <option value="none">None (bare container)</option>
                <option value="wazuh">Wazuh</option>
                <option value="ossec">OSSEC</option>
                <option value="ossim">OSSIM</option>
                <option value="utmstack">UTMstack</option>
                <option value="elastic">Elastic</option>
              </select>
            </div>
            {!isBare && (
              <div className="field">
                <label htmlFor="deploy-siem-manager-ip">SIEM Manager IP</label>
                <input id="deploy-siem-manager-ip" className="input" placeholder="192.168.1.100" value={form.siem_ip} onChange={(e) => set("siem_ip", e.target.value)} required />
              </div>
            )}
            {!isBare && !needsAuthKey && (
              <div className="field">
                <label htmlFor="deploy-siem-version">SIEM Version</label>
                <input id="deploy-siem-version" className="input" value={form.siem_version} onChange={(e) => set("siem_version", e.target.value)} />
              </div>
            )}
            {isElastic && (
              <div className="field">
                <label htmlFor="deploy-agent-version">Agent Version</label>
                <input id="deploy-agent-version" className="input" value={form.siem_version || "9.0.2"} onChange={(e) => set("siem_version", e.target.value)} />
              </div>
            )}
            {needsAuthKey && (
              <div className="field">
                <label>{isElastic ? "Enrollment Token" : "Installer Auth Key"}</label>
                <input className="input"
                  placeholder={selectedManager?.has_siem_auth_key
                    ? `From profile (${selectedManager.siem_auth_key_hint}) — type to override`
                    : isElastic ? "Fleet enrollment token" : "UTMstack auth key"}
                  value={form.siem_auth_key} onChange={(e) => set("siem_auth_key", e.target.value)}
                  required={!selectedManager?.has_siem_auth_key} />
              </div>
            )}
            <div className="field">
              <label htmlFor="deploy-os-type">OS Type</label>
              <select id="deploy-os-type" className="select" value={form.os_type} onChange={(e) => set("os_type", e.target.value)}>
                <option value="ubuntu_22_04">Ubuntu 22.04</option>
                <option value="ubuntu_20_04">Ubuntu 20.04</option>
                <option value="debian_11">Debian 11</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="deploy-container-group">Container Group</label>
              <input id="deploy-container-group" className="input" value={form.agent_group} onChange={(e) => set("agent_group", e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="deploy-base-name">Base Name</label>
              <input id="deploy-base-name" className="input" value={form.agent_base_name} onChange={(e) => set("agent_base_name", e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="deploy-memory-limit">Memory Limit</label>
              <input id="deploy-memory-limit" className="input" value={form.memory_limit} onChange={(e) => set("memory_limit", e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="deploy-cpu-shares">CPU Shares</label>
              <input id="deploy-cpu-shares" className="input" type="number" min={2} max={10240} value={form.cpu_shares} onChange={(e) => set("cpu_shares", e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="deploy-config-template-id">Config Template ID</label>
              <input id="deploy-config-template-id" className="input" placeholder="optional template id" value={form.config_template_id} onChange={(e) => set("config_template_id", e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="deploy-parallel-mode">Parallel Mode</label>
              <select id="deploy-parallel-mode" className="select" value={form.parallel_mode} onChange={(e) => set("parallel_mode", e.target.value)}>
                <option value="multiprocessing">Multiprocessing</option>
                <option value="threading">Threading</option>
                <option value="sequential">Sequential</option>
              </select>
            </div>
          </div>
          <div style={{ marginTop: 16, display: "flex", gap: 16, flexWrap: "wrap", alignItems: "center" }}>
            <label className="checkbox-label"><input type="checkbox" checked={form.autostart} onChange={(e) => set("autostart", e.target.checked)} /> Auto-start</label>
            <label className="checkbox-label"><input type="checkbox" checked={form.auto_create_group} onChange={(e) => set("auto_create_group", e.target.checked)} /> Auto-create group</label>
          </div>
        </div>
        <button className="btn btn-primary" type="submit" disabled={deploying}>
          {deploying ? "Deploying..." : `Deploy ${form.count} Container${form.count > 1 ? "s" : ""}`}
        </button>
      </form>

      {progress && <DeployActivity progress={progress} active={deploying} />}

      {result && (
        <details className="section" style={{ marginTop: 20 }}>
          <summary className="section-title" style={{ cursor: "pointer" }}>Full deployment result</summary>
          <div className="card">
            {result.message && <p>{result.message}</p>}
            <Details data={result.data || result} />
          </div>
        </details>
      )}
    </>
  );
}

// Server events replace the local placeholder, but keep the "sending" line at the top
function mergeProgress(prev, server) {
  const localHead = prev?.local ? prev.events.slice(0, 1) : prev?.localHead || [];
  return { ...server, events: [...localHead, ...server.events], localHead, local: false };
}

function finishLocal(prev, message, success) {
  if (!prev) return prev;
  return {
    ...prev,
    status: success ? "completed" : "failed",
    finished_at: new Date().toISOString(),
    events: [...prev.events, localEvent(message, success ? "success" : "error")],
  };
}
