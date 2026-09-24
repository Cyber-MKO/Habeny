import { useEffect, useState, useCallback } from "react";
import { api } from "../api";
import { useStore } from "../store";
import { PageHeader, DataTable, Spinner } from "../components/UI";
import { useConfirm } from "../components/Confirm";
import { Details } from "../components/Details";
import { t } from "../i18n";

export default function SyslogConfigs() {
  const { toast } = useStore();
  const confirm = useConfirm();
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
        toast(t("Syslog config updated"), "success");
        setEditing(null);
      } else {
        await api.createSyslogConfig(payload);
        toast(t("Syslog config created"), "success");
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
    if (!(await confirm({ title: t("Delete this syslog config?"), confirmLabel: t("Delete config"), danger: true }))) return;
    try { await api.deleteSyslogConfig(id); toast(t("Deleted"), "success"); load(); }
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
    if (!enableAgent) return toast(t("Select a container"), "error");
    try {
      const res = await api.enableUtmSyslog(enableAgent, enableProto);
      toast(res.message, res.success ? "success" : "error");
      if (res.success) load();
    } catch (e) { toast(e.message, "error"); }
  };

  const handleDisableSyslog = async () => {
    if (!enableAgent) return toast(t("Select a container"), "error");
    try {
      const res = await api.disableUtmSyslog(enableAgent, enableProto);
      toast(res.message, res.success ? "success" : "error");
    } catch (e) { toast(e.message, "error"); }
  };

  const cancelEdit = () => { setEditing(null); setForm({ name: "", description: "", manager_profile_id: "", target_ip: "", target_port: 514, protocol: "tcp", siem_type: "" }); };

  const utmAgents = agents.filter((a) => a.siem_type === "utmstack" && a.lifecycle_status === "running");

  const columns = [
    { key: "name", label: t("Name") },
    { key: "target_ip", label: t("Target IP") },
    { key: "target_port", label: t("Port") },
    { key: "protocol", label: t("Protocol"), render: (r) => (r.protocol || "tcp").toUpperCase() },
    { key: "siem_type", label: "SIEM", render: (r) => r.siem_type || "—" },
    { key: "actions", label: t("Actions"), render: (r) => (
      <div className="btn-group">
        <button className="btn btn-sm btn-secondary" onClick={() => handleTest(r.target_ip, r.target_port, r.protocol)}>{t("Test")}</button>
        <button className="btn btn-sm btn-secondary" onClick={() => handleEdit(r)}>{t("Edit")}</button>
        <button className="btn btn-sm btn-danger" onClick={() => handleDelete(r.config_id)}>{t("Delete")}</button>
      </div>
    )},
  ];

  return (
    <>
      <PageHeader title={t("Syslog Config")} subtitle={t("Syslog forwarding profiles and connectivity testing")}>
        <button className="btn btn-secondary" onClick={load}>{t("Refresh")}</button>
      </PageHeader>

      <form onSubmit={handleSave} className="card" style={{ marginBottom: 20 }}>
        <div className="section-title">{editing ? t("Edit Syslog Config") : t("Create Syslog Config")}</div>
        <div className="form-grid">
          <div className="field"><label htmlFor="syslog-configs-profile-name">{t("Profile Name")}</label><input id="syslog-configs-profile-name" className="input" value={form.name} onChange={(e) => set("name", e.target.value)} required /></div>
          <div className="field">
            <label htmlFor="syslog-configs-link-to-manager-profile">{t("Link to Manager Profile")}</label>
            <select id="syslog-configs-link-to-manager-profile" className="select" value={form.manager_profile_id} onChange={(e) => applyManager(e.target.value)}>
              <option value="">{t("— none —")}</option>
              {managers.map((m) => <option key={m.manager_id} value={m.manager_id}>{m.name} ({m.siem_ip || "—"})</option>)}
            </select>
          </div>
          <div className="field"><label htmlFor="syslog-configs-target-ip">{t("Target IP")}</label><input id="syslog-configs-target-ip" className="input" value={form.target_ip} onChange={(e) => set("target_ip", e.target.value)} required /></div>
          <div className="field"><label htmlFor="syslog-configs-port">{t("Port")}</label><input id="syslog-configs-port" className="input" type="number" min={1} max={65535} value={form.target_port} onChange={(e) => set("target_port", e.target.value)} /></div>
          <div className="field">
            <label htmlFor="syslog-configs-protocol">{t("Protocol")}</label>
            <select id="syslog-configs-protocol" className="select" value={form.protocol} onChange={(e) => set("protocol", e.target.value)}><option value="tcp">TCP</option><option value="udp">UDP</option></select>
          </div>
          <div className="field">
            <label htmlFor="syslog-configs-siem-type">{t("SIEM Type")}</label>
            <select id="syslog-configs-siem-type" className="select" value={form.siem_type} onChange={(e) => set("siem_type", e.target.value)}>
              <option value="">{t("— any —")}</option>
              <option value="wazuh">Wazuh</option><option value="ossec">OSSEC</option><option value="utmstack">UTMstack</option><option value="elastic">Elastic</option>
            </select>
          </div>
          <div className="field"><label htmlFor="syslog-configs-description">{t("Description")}</label><input id="syslog-configs-description" className="input" value={form.description} onChange={(e) => set("description", e.target.value)} /></div>
        </div>
        <div className="btn-group" style={{ marginTop: 12 }}>
          <button className="btn btn-primary" type="submit">{editing ? t("Update") : t("Create")}</button>
          <button className="btn btn-secondary" type="button" onClick={() => handleTest()}>{t("Test Connectivity")}</button>
          {editing && <button className="btn btn-secondary" type="button" onClick={cancelEdit}>{t("Cancel")}</button>}
        </div>
      </form>

      {testResult && (<div className="card" style={{ marginBottom: 16 }}><div className="section-title">{t("Test Result")}</div><Details data={testResult.data || testResult} /></div>)}

      <div className="card" style={{ marginBottom: 20 }}>
        <div className="section-title">{t("Saved Syslog Configs")}</div>
        {loading ? <Spinner /> : <DataTable columns={columns} rows={configs} emptyMsg={t("No syslog configs. Create one above.")} />}
      </div>

      {utmAgents.length > 0 && (
        <div className="card">
          <div className="section-title">{t("Enable UTMstack Syslog Listener (port 7014)")}</div>
          <p style={{ fontSize: 12, color: "var(--text-dim)", marginBottom: 12 }}>{t("Enable syslog integration on a UTMstack container so it listens for syslog on port 7014.")}</p>
          <div className="form-grid">
            <div className="field"><label htmlFor="syslog-configs-container">{t("Container")}</label>
              <select id="syslog-configs-container" className="select" value={enableAgent} onChange={(e) => setEnableAgent(e.target.value)}>
                <option value="">{t("— select UTMstack container —")}</option>
                {utmAgents.map((a) => <option key={a.agent_name} value={a.agent_name}>{a.agent_name}</option>)}
              </select>
            </div>
            <div className="field"><label htmlFor="syslog-configs-protocol-2">{t("Protocol")}</label>
              <select id="syslog-configs-protocol-2" className="select" value={enableProto} onChange={(e) => setEnableProto(e.target.value)}><option value="tcp">TCP</option><option value="udp">UDP</option></select>
            </div>
            <div className="field" style={{ justifyContent: "flex-end" }}>
              <div className="btn-group">
                <button className="btn btn-primary" onClick={handleEnableSyslog}>{t("Enable")}</button>
                <button className="btn btn-danger" onClick={handleDisableSyslog}>{t("Disable")}</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
