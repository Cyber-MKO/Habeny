import { useState, useEffect } from "react";
import { api } from "../api";
import { useStore } from "../store";
import { PageHeader, JsonBlock } from "../components/UI";

const DEFAULTS = {
  count: 2, siem_type: "none", siem_ip: "", siem_version: "4.14.2", siem_auth_key: "",
  os_type: "ubuntu_22_04", agent_group: "default", agent_base_name: "container",
  memory_limit: "512MB", cpu_shares: 1024, config_template_id: "",
  autostart: true, auto_create_group: true, parallel_mode: "multiprocessing",
  manager_profile_id: "",
};

export default function Deploy() {
  const { toast } = useStore();
  const [form, setForm] = useState(DEFAULTS);
  const [result, setResult] = useState(null);
  const [deploying, setDeploying] = useState(false);
  const [managers, setManagers] = useState([]);

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
      siem_auth_key: mgr.siem_auth_key || "",
      os_type: mgr.os_type || p.os_type,
      agent_group: mgr.agent_group || p.agent_group,
      memory_limit: mgr.memory_limit || p.memory_limit,
      cpu_shares: mgr.cpu_shares || p.cpu_shares,
      config_template_id: mgr.config_template_id || "",
    }));
  };

  const isBare = form.siem_type === "none";
  const isUtm = form.siem_type === "utmstack";
  const isElastic = form.siem_type === "elastic";
  const needsAuthKey = isUtm || isElastic;

  const handleSubmit = async (e) => {
    e.preventDefault();
    setDeploying(true);
    setResult(null);
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
      };
      if (form.manager_profile_id) payload.manager_profile_id = form.manager_profile_id;
      if (!isBare) {
        payload.siem_ip = form.siem_ip;
        if (!needsAuthKey || isElastic) payload.siem_version = form.siem_version;
        if (needsAuthKey) payload.siem_auth_key = form.siem_auth_key;
      }
      const res = await api.deploy(payload);
      setResult(res);
      toast(res.message || "Deployment complete", res.success ? "success" : "error");
    } catch (err) {
      setResult({ error: err.message });
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
              <label>Manager Profile</label>
              <select className="select" value={form.manager_profile_id} onChange={(e) => applyManager(e.target.value)}>
                <option value="">— Manual configuration —</option>
                {managers.map((m) => <option key={m.manager_id} value={m.manager_id}>{m.name} ({m.siem_type} — {m.siem_ip || "no IP"})</option>)}
              </select>
            </div>
            <div className="field">
              <label>Container Count</label>
              <input className="input" type="number" min={1} max={1000} value={form.count} onChange={(e) => set("count", e.target.value)} />
            </div>
            <div className="field">
              <label>SIEM Type</label>
              <select className="select" value={form.siem_type} onChange={(e) => set("siem_type", e.target.value)}>
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
                <label>SIEM Manager IP</label>
                <input className="input" placeholder="192.168.1.100" value={form.siem_ip} onChange={(e) => set("siem_ip", e.target.value)} required />
              </div>
            )}
            {!isBare && !needsAuthKey && (
              <div className="field">
                <label>SIEM Version</label>
                <input className="input" value={form.siem_version} onChange={(e) => set("siem_version", e.target.value)} />
              </div>
            )}
            {isElastic && (
              <div className="field">
                <label>Agent Version</label>
                <input className="input" value={form.siem_version || "9.0.2"} onChange={(e) => set("siem_version", e.target.value)} />
              </div>
            )}
            {needsAuthKey && (
              <div className="field">
                <label>{isElastic ? "Enrollment Token" : "Installer Auth Key"}</label>
                <input className="input" placeholder={isElastic ? "Fleet enrollment token" : "UTMstack auth key"} value={form.siem_auth_key} onChange={(e) => set("siem_auth_key", e.target.value)} required />
              </div>
            )}
            <div className="field">
              <label>OS Type</label>
              <select className="select" value={form.os_type} onChange={(e) => set("os_type", e.target.value)}>
                <option value="ubuntu_22_04">Ubuntu 22.04</option>
                <option value="ubuntu_20_04">Ubuntu 20.04</option>
                <option value="debian_11">Debian 11</option>
              </select>
            </div>
            <div className="field">
              <label>Container Group</label>
              <input className="input" value={form.agent_group} onChange={(e) => set("agent_group", e.target.value)} />
            </div>
            <div className="field">
              <label>Base Name</label>
              <input className="input" value={form.agent_base_name} onChange={(e) => set("agent_base_name", e.target.value)} />
            </div>
            <div className="field">
              <label>Memory Limit</label>
              <input className="input" value={form.memory_limit} onChange={(e) => set("memory_limit", e.target.value)} />
            </div>
            <div className="field">
              <label>CPU Shares</label>
              <input className="input" type="number" min={2} max={10240} value={form.cpu_shares} onChange={(e) => set("cpu_shares", e.target.value)} />
            </div>
            <div className="field">
              <label>Config Template ID</label>
              <input className="input" placeholder="optional template id" value={form.config_template_id} onChange={(e) => set("config_template_id", e.target.value)} />
            </div>
            <div className="field">
              <label>Parallel Mode</label>
              <select className="select" value={form.parallel_mode} onChange={(e) => set("parallel_mode", e.target.value)}>
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

      {result && (
        <div className="section" style={{ marginTop: 20 }}>
          <div className="section-title">Deployment Result</div>
          <JsonBlock data={result} />
        </div>
      )}
    </>
  );
}
