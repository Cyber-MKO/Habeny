import { useEffect, useState, useCallback } from "react";
import { api } from "../api";
import { useStore } from "../store";
import { PageHeader, DataTable, Pill, Spinner, Modal, JsonBlock } from "../components/UI";

export default function SyslogConfigs() {
  const { toast } = useStore();
  const [configs, setConfigs] = useState([]);
  const [managers, setManagers] = useState([]);
  const [agents, setAgents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState({ name: "", description: "", manager_profile_id: "", target_ip: "", target_port: 514, protocol: "tcp", siem_type: "" });
  const [editing, setEditing] = useState(null);
  const [testResult, setTestResult] = useState(null);

  const [enableAgent, setEnableAgent] = useState("");
  const [enableProto, setEnableProto] = useState("tcp");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [c, m, a] = await Promise.all([
        api.getSyslogConfigs(),
        api.getManagers().catch(() => ({ data: { managers: [] } })),
        api.getAgents({ limit: 1000 }).catch(() => ({ data: { agents: [] } })),
      ]);
      setConfigs(c.data?.configs || []);
      setManagers(m.data?.managers || []);
      setAgents(a.data?.agents || []);
    } catch (e) { toast(e.message, "error"); }
    finally { setLoading(false); }
  }, [toast]);

  useEffect(() => { load(); }, [load]);

  const set = (k, v) => setForm((p) => ({ ...p, [k]: v }));

  const applyManager = (mgr_id) => {
    set("manager_profile_id", mgr_id);
    const mgr = managers.find((m) => m.manager_id === mgr_id);
    if (mgr?.siem_ip) set("target_ip", mgr.siem_ip);
    if (mgr?.siem_type) set("siem_type", mgr.siem_type);
  };

  const handleSave = async (e) => {
    e.preventDefault();
    const payload = { ...form, target_port: Number(form.target_port) };
    if (!payload.manager_profile_id) delete payload.manager_profile_id;
    if (!payload.description) delete payload.description;
    if (!payload.siem_type) delete payload.siem_type;
    try {
      if (editing) {
        await api.updateSyslogConfig(editing, payload);
        toast("Syslog config updated", "success");
        setEditing(null);
      } else {
        await api.createSyslogConfig(payload);
        toast("Syslog config created", "success");
      }
      setForm({ name: "", description: "", manager_profile_id: "", target_ip: "", target_port: 514, protocol: "tcp", siem_type: "" });
      load();
    } catch (e) { toast(e.message, "error"); }
  };

  const handleEdit = (cfg) => {
    setEditing(cfg.config_id);
    setForm({
      name: cfg.name || "", description: cfg.description || "",
      manager_profile_id: cfg.manager_profile_id || "",
      target_ip: cfg.target_ip || "", target_port: cfg.target_port || 514,
      protocol: cfg.protocol || "tcp", siem_type: cfg.siem_type || "",
    });
  };

  const handleDelete = async (id) => {
    if (!confirm("Delete this syslog config?")) return;
    try { await api.deleteSyslogConfig(id); toast("Deleted", "success"); load(); }
    catch (e) { toast(e.message, "error"); }
  };

  const handleTest = async (ip, port, proto) => {
    setTestResult(null);
    try {
      const res = await api.testSyslogConnectivity({ target_ip: ip || form.target_ip, target_port: port || form.target_port, protocol: proto || form.protocol });
      setTestResult(res);
      toast(res.message, res.success ? "success" : "error");
    } catch (e) { toast(e.message, "error"); }
  };

  const handleEnableSyslog = async () => {
    if (!enableAgent) return toast("Select a container", "error");
    try {
      const res = await api.enableUtmSyslog(enableAgent, enableProto);
      toast(res.message, res.success ? "success" : "error");
      if (res.success) load();
    } catch (e) { toast(e.message, "error"); }
  };

  const handleDisableSyslog = async () => {
    if (!enableAgent) return toast("Select a container", "error");
    try {
      const res = await api.disableUtmSyslog(enableAgent, enableProto);
      toast(res.message, res.success ? "success" : "error");
    } catch (e) { toast(e.message, "error"); }
  };

  const cancelEdit = () => { setEditing(null); setForm({ name: "", description: "", manager_profile_id: "", target_ip: "", target_port: 514, protocol: "tcp", siem_type: "" }); };

  const utmAgents = agents.filter((a) => a.siem_type === "utmstack" && a.lifecycle_status === "running");

  const columns = [
    { key: "name", label: "Name" },
    { key: "target_ip", label: "Target IP" },
    { key: "target_port", label: "Port" },
    { key: "protocol", label: "Protocol", render: (r) => (r.protocol || "tcp").toUpperCase() },
    { key: "siem_type", label: "SIEM", render: (r) => r.siem_type || "—" },
    { key: "actions", label: "Actions", render: (r) => (
      <div className="btn-group">
        <button className="btn btn-sm btn-secondary" onClick={() => handleTest(r.target_ip, r.target_port, r.protocol)}>Test</button>
        <button className="btn btn-sm btn-secondary" onClick={() => handleEdit(r)}>Edit</button>
        <button className="btn btn-sm btn-danger" onClick={() => handleDelete(r.config_id)}>Delete</button>
      </div>
    )},
  ];

  return (
    <>
      <PageHeader title="Syslog Config" subtitle="Syslog forwarding profiles and connectivity testing">
        <button className="btn btn-secondary" onClick={load}>Refresh</button>
      </PageHeader>

      <form onSubmit={handleSave} className="card" style={{ marginBottom: 20 }}>
        <div className="section-title">{editing ? "Edit Syslog Config" : "Create Syslog Config"}</div>
        <div className="form-grid">
          <div className="field"><label>Profile Name</label><input className="input" value={form.name} onChange={(e) => set("name", e.target.value)} required /></div>
          <div className="field">
            <label>Link to Manager Profile</label>
            <select className="select" value={form.manager_profile_id} onChange={(e) => applyManager(e.target.value)}>
              <option value="">— none —</option>
              {managers.map((m) => <option key={m.manager_id} value={m.manager_id}>{m.name} ({m.siem_ip || "—"})</option>)}
            </select>
          </div>
          <div className="field"><label>Target IP</label><input className="input" value={form.target_ip} onChange={(e) => set("target_ip", e.target.value)} required /></div>
          <div className="field"><label>Port</label><input className="input" type="number" min={1} max={65535} value={form.target_port} onChange={(e) => set("target_port", e.target.value)} /></div>
          <div className="field">
            <label>Protocol</label>
            <select className="select" value={form.protocol} onChange={(e) => set("protocol", e.target.value)}><option value="tcp">TCP</option><option value="udp">UDP</option></select>
          </div>
          <div className="field">
            <label>SIEM Type</label>
            <select className="select" value={form.siem_type} onChange={(e) => set("siem_type", e.target.value)}>
              <option value="">— any —</option>
              <option value="wazuh">Wazuh</option><option value="ossec">OSSEC</option><option value="utmstack">UTMstack</option><option value="elastic">Elastic</option>
            </select>
          </div>
          <div className="field"><label>Description</label><input className="input" value={form.description} onChange={(e) => set("description", e.target.value)} /></div>
        </div>
        <div className="btn-group" style={{ marginTop: 12 }}>
          <button className="btn btn-primary" type="submit">{editing ? "Update" : "Create"}</button>
          <button className="btn btn-secondary" type="button" onClick={() => handleTest()}>Test Connectivity</button>
          {editing && <button className="btn btn-secondary" type="button" onClick={cancelEdit}>Cancel</button>}
        </div>
      </form>

      {testResult && (<div className="card" style={{ marginBottom: 16 }}><div className="section-title">Test Result</div><JsonBlock data={testResult} /></div>)}

      <div className="card" style={{ marginBottom: 20 }}>
        <div className="section-title">Saved Syslog Configs</div>
        {loading ? <Spinner /> : <DataTable columns={columns} rows={configs} emptyMsg="No syslog configs. Create one above." />}
      </div>

      {utmAgents.length > 0 && (
        <div className="card">
          <div className="section-title">Enable UTMstack Syslog Listener (port 7014)</div>
          <p style={{ fontSize: 12, color: "var(--text-dim)", marginBottom: 12 }}>Enable syslog integration on a UTMstack container so it listens for syslog on port 7014.</p>
          <div className="form-grid">
            <div className="field"><label>Container</label>
              <select className="select" value={enableAgent} onChange={(e) => setEnableAgent(e.target.value)}>
                <option value="">— select UTMstack container —</option>
                {utmAgents.map((a) => <option key={a.agent_name} value={a.agent_name}>{a.agent_name}</option>)}
              </select>
            </div>
            <div className="field"><label>Protocol</label>
              <select className="select" value={enableProto} onChange={(e) => setEnableProto(e.target.value)}><option value="tcp">TCP</option><option value="udp">UDP</option></select>
            </div>
            <div className="field" style={{ justifyContent: "flex-end" }}>
              <div className="btn-group">
                <button className="btn btn-primary" onClick={handleEnableSyslog}>Enable</button>
                <button className="btn btn-danger" onClick={handleDisableSyslog}>Disable</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
