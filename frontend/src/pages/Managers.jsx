import { useEffect, useState, useCallback } from "react";
import { api } from "../api";
import { useStore } from "../store";
import { PageHeader, DataTable, Pill, Spinner, Modal } from "../components/UI";
import { useConfirm } from "../components/Confirm";
import { useAuth } from "../auth";
import { Details } from "../components/Details";
import { t } from "../i18n";

const SIEM_TYPES = ["wazuh", "ossec", "utmstack", "elastic", "none"];
const OS_TYPES = ["ubuntu_22_04", "ubuntu_24_04", "debian_12"];

const EMPTY_FORM = {
  name: "", description: "", siem_type: "wazuh", siem_ip: "", siem_version: "4.14.2",
  siem_auth_key: "", os_type: "ubuntu_22_04", agent_group: "default",
  memory_limit: "512MB", cpu_shares: 1024, config_template_id: "",
  detection_url: "", detection_username: "", detection_secret: "",
  syslog_port: "", syslog_protocol: "tcp",
};

// SIEMs whose search API Habeny can ask what they detected (app/services/detection.py)
const DETECTION_SIEMS = ["wazuh", "elastic"];

// Test the saved detection connection; a self-signed certificate is shown for an admin to trust
function DetectionTest({ manager, onSaved }) {
  const { toast } = useStore();
  const [pending, setPending] = useState(null);
  const [busy, setBusy] = useState(false);
  const test = async () => {
    setBusy(true);
    try {
      toast((await api.testDetection(manager.manager_id)).message, "success");
      setPending(null);
    } catch (err) {
      if (err.status === 409 && err.data?.fingerprint) setPending(err.data.fingerprint);
      else toast(err.message, "error");
    } finally { setBusy(false); }
  };
  const trust = async () => {
    try {
      await api.updateManager(manager.manager_id, { detection_fingerprint: pending });
      setPending(null);
      onSaved();
      toast(t("Certificate trusted. Testing again…"), "info");
      await test();
    } catch (err) { toast(err.message, "error"); }
  };
  return (
    <div className="detection-test">
      <button type="button" className="btn btn-sm btn-secondary" onClick={test} disabled={busy}>{busy ? t("Testing…") : t("Test detection connection")}</button>
      {pending && (
        <div className="auth-hint" role="alert">
          {t("The SIEM's certificate isn't from a trusted authority. Trust it only if this fingerprint matches the SIEM's certificate:")}
          <code className="fingerprint">{pending}</code>
          <button type="button" className="btn btn-sm btn-primary" onClick={trust}>{t("Trust this certificate")}</button>
        </div>
      )}
    </div>
  );
}

function SyslogTest({ manager }) {
  const { toast } = useStore();
  const [busy, setBusy] = useState(false);
  const test = async () => {
    setBusy(true);
    try { const res = await api.testSyslog(manager.manager_id); toast(res.message, res.success ? "success" : "error"); }
    catch (err) { toast(err.message, "error"); }
    finally { setBusy(false); }
  };
  return <button type="button" className="btn btn-sm btn-secondary" onClick={test} disabled={busy}>{busy ? t("Testing…") : t("Test syslog port")}</button>;
}

export default function Managers() {
  const { toast } = useStore();
  const { user } = useAuth();
  const confirm = useConfirm();
  const [managers, setManagers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState({ ...EMPTY_FORM });
  const [editing, setEditing] = useState(null);
  const [viewData, setViewData] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try { const res = await api.getManagers(); setManagers(res.data?.managers || []); }
    catch (e) { toast(e.message, "error"); }
    finally { setLoading(false); }
  }, [toast]);

  useEffect(() => { load(); }, [load]);

  const set = (k, v) => setForm((p) => ({ ...p, [k]: v }));
  const isBare = form.siem_type === "none";
  const isUtm = form.siem_type === "utmstack";
  const isElastic = form.siem_type === "elastic";
  const needsAuthKey = isUtm || isElastic;
  const canDetect = user?.is_admin && DETECTION_SIEMS.includes(form.siem_type);

  const handleSave = async (e) => {
    e.preventDefault();
    const payload = { ...form };
    payload.cpu_shares = Number(payload.cpu_shares);
    if (payload.syslog_port) payload.syslog_port = Number(payload.syslog_port);
    else if (editing) { payload.syslog_port = null; delete payload.syslog_protocol; } // blank turns syslog off
    else { delete payload.syslog_port; delete payload.syslog_protocol; }
    if (!payload.siem_ip && isBare) delete payload.siem_ip;
    if (!payload.siem_version || isBare || isUtm) delete payload.siem_version;
    if (!payload.siem_auth_key) delete payload.siem_auth_key;
    if (!payload.config_template_id) delete payload.config_template_id;
    if (!payload.description) delete payload.description;
    if (!canDetect) {
      delete payload.detection_url; delete payload.detection_username; delete payload.detection_secret;
    } else if (!payload.detection_secret) delete payload.detection_secret; // blank keeps the stored one

    try {
      if (editing) {
        await api.updateManager(editing, payload);
        toast(t("SIEM target updated"), "success");
        setEditing(null);
      } else {
        await api.createManager(payload);
        toast(t("SIEM target created"), "success");
      }
      setForm({ ...EMPTY_FORM });
      load();
    } catch (e) { toast(e.message, "error"); }
  };

  const handleEdit = (mgr) => {
    setEditing(mgr.manager_id);
    setForm({
      name: mgr.name || "", description: mgr.description || "",
      siem_type: mgr.siem_type || "wazuh", siem_ip: mgr.siem_ip || "",
      siem_version: mgr.siem_version || "", siem_auth_key: "", // write-only: blank keeps the stored key
      os_type: mgr.os_type || "ubuntu_22_04", agent_group: mgr.agent_group || "default",
      memory_limit: mgr.memory_limit || "512MB", cpu_shares: mgr.cpu_shares || 1024,
      config_template_id: mgr.config_template_id || "",
      detection_url: mgr.detection_url || "", detection_username: mgr.detection_username || "", detection_secret: "",
      syslog_port: mgr.syslog_port || "", syslog_protocol: mgr.syslog_protocol || "tcp",
    });
  };

  const handleDelete = async (id) => {
    if (!(await confirm({ title: t("Delete this SIEM target?"), message: t("Containers already deployed with it aren't affected."), confirmLabel: t("Delete target"), danger: true }))) return;
    try { await api.deleteManager(id); toast(t("Deleted"), "success"); load(); }
    catch (e) { toast(e.message, "error"); }
  };

  const editingManager = editing ? managers.find((m) => m.manager_id === editing) : null;
  const editingKeyHint = editingManager?.siem_auth_key_hint;

  const cancelEdit = () => { setEditing(null); setForm({ ...EMPTY_FORM }); };

  const columns = [
    { key: "name", label: t("Name") },
    { key: "siem_type", label: t("SIEM Type"), render: (r) => <Pill status={r.siem_type === "none" ? "unknown" : r.siem_type} /> },
    { key: "siem_ip", label: t("Address"), render: (r) => r.siem_ip || "—" },
    { key: "syslog_port", label: "Syslog", render: (r) => r.syslog_port ? `${r.syslog_port}/${(r.syslog_protocol || "tcp").toUpperCase()}` : "—" },
    { key: "siem_auth_key_hint", label: t("Auth Key"), render: (r) => r.has_siem_auth_key ? <span style={{ fontFamily: "var(--font-mono)" }}>{r.siem_auth_key_hint}</span> : "—" },
    { key: "agent_group", label: t("Group") },
    { key: "detection_configured", label: t("Detection API"), render: (r) => r.detection_configured ? t("Set") : "—" },
    { key: "created_at", label: t("Created"), render: (r) => r.created_at ? new Date(r.created_at).toLocaleDateString() : "—" },
    { key: "actions", label: t("Actions"), render: (r) => (
      <div className="btn-group">
        <button className="btn btn-sm btn-secondary" onClick={() => setViewData(r)}>{t("View")}</button>
        {r.syslog_port && <SyslogTest manager={r} />}
        <button className="btn btn-sm btn-secondary" onClick={() => handleEdit(r)}>{t("Edit")}</button>
        <button className="btn btn-sm btn-danger" onClick={() => handleDelete(r.manager_id)}>{t("Delete")}</button>
      </div>
    )},
  ];

  return (
    <>
      <PageHeader title={t("SIEM Targets")} subtitle={t("Each SIEM you test: agent settings for deploying, its syslog port, and its detection API")}>
        <button className="btn btn-secondary" onClick={load}>{t("Refresh")}</button>
      </PageHeader>

      <form onSubmit={handleSave} className="card" style={{ marginBottom: 20 }}>
        <div className="section-title">{editing ? t("Edit SIEM target") : t("Add a SIEM target")}</div>
        <div className="form-grid">
          <div className="field"><label htmlFor="managers-profile-name">{t("Profile Name")}</label><input id="managers-profile-name" className="input" value={form.name} onChange={(e) => set("name", e.target.value)} required /></div>
          <div className="field"><label htmlFor="managers-description">{t("Description")}</label><input id="managers-description" className="input" value={form.description} onChange={(e) => set("description", e.target.value)} /></div>
          <div className="field"><label htmlFor="managers-siem-type">{t("SIEM Type")}</label>
            <select id="managers-siem-type" className="select" value={form.siem_type} onChange={(e) => set("siem_type", e.target.value)}>
              {SIEM_TYPES.map((type) => <option key={type} value={type}>{type === "none" ? t("Other (syslog only, or bare containers)") : type.charAt(0).toUpperCase() + type.slice(1)}</option>)}
            </select>
          </div>
          <div className="field"><label htmlFor="managers-manager-ip-hostname">{isBare ? t("Address (for syslog)") : t("Manager IP / Hostname")}</label><input id="managers-manager-ip-hostname" className="input" value={form.siem_ip} onChange={(e) => set("siem_ip", e.target.value)} /></div>
          {!isBare && !needsAuthKey && <div className="field"><label htmlFor="managers-siem-version">{t("SIEM Version")}</label><input id="managers-siem-version" className="input" value={form.siem_version} onChange={(e) => set("siem_version", e.target.value)} /></div>}
          {isElastic && <div className="field"><label htmlFor="managers-agent-version">{t("Agent Version")}</label><input id="managers-agent-version" className="input" value={form.siem_version || "9.0.2"} onChange={(e) => set("siem_version", e.target.value)} /></div>}
          {needsAuthKey && <div className="field"><label>{isElastic ? t("Enrollment Token") : t("Auth Key")}</label><input className="input" type="password" autoComplete="off" value={form.siem_auth_key} onChange={(e) => set("siem_auth_key", e.target.value)}
            placeholder={editingKeyHint ? t("Stored ({editingKeyHint}) — leave blank to keep", { editingKeyHint }) : ""} /></div>}
          <div className="field"><label htmlFor="managers-os-type">{t("OS Type")}</label>
            <select id="managers-os-type" className="select" value={form.os_type} onChange={(e) => set("os_type", e.target.value)}>
              {OS_TYPES.map((os) => <option key={os} value={os}>{os}</option>)}
            </select>
          </div>
          <div className="field"><label htmlFor="managers-agent-group">{t("Agent Group")}</label><input id="managers-agent-group" className="input" value={form.agent_group} onChange={(e) => set("agent_group", e.target.value)} /></div>
          <div className="field"><label htmlFor="managers-memory-limit">{t("Memory Limit")}</label><input id="managers-memory-limit" className="input" value={form.memory_limit} onChange={(e) => set("memory_limit", e.target.value)} /></div>
          <div className="field"><label htmlFor="managers-cpu-shares">{t("CPU Shares")}</label><input id="managers-cpu-shares" className="input" type="number" min={2} max={10240} value={form.cpu_shares} onChange={(e) => set("cpu_shares", e.target.value)} /></div>
          <div className="field"><label htmlFor="managers-config-template-id">{t("Config Template ID")}</label><input id="managers-config-template-id" className="input" value={form.config_template_id} onChange={(e) => set("config_template_id", e.target.value)} /></div>
        </div>
        <fieldset className="detection-fields">
          <legend>{t("Syslog (optional)")}</legend>
          <p className="auth-hint">{t("The port this SIEM receives syslog on, at the address above. Syslog simulations can then send to it. Leave empty if it doesn't take syslog.")}</p>
          <div className="form-grid">
            <div className="field"><label htmlFor="managers-syslog-port">{t("Syslog port")}</label><input id="managers-syslog-port" className="input" type="number" min={1} max={65535} placeholder="514" value={form.syslog_port} onChange={(e) => set("syslog_port", e.target.value)} /></div>
            <div className="field"><label htmlFor="managers-syslog-protocol">{t("Protocol")}</label>
              <select id="managers-syslog-protocol" className="select" value={form.syslog_protocol} onChange={(e) => set("syslog_protocol", e.target.value)} disabled={!form.syslog_port}>
                <option value="tcp">TCP</option><option value="udp">UDP</option>
              </select>
            </div>
          </div>
          {editingManager?.syslog_port && <SyslogTest manager={editingManager} />}
        </fieldset>
        {canDetect && (
          <fieldset className="detection-fields">
            <legend>{t("Detection API (optional)")}</legend>
            <p className="auth-hint">
              {form.siem_type === "wazuh"
                ? t("The Wazuh indexer's address (usually https://<indexer>:9200) and a user that can read wazuh-alerts-*. After attack simulations, Habeny asks it which alerts fired.")
                : t("The Elasticsearch address (usually https://<host>:9200), and a user and password or an API key that can read .alerts-security.alerts-* and logs-*.")}
            </p>
            <div className="form-grid">
              <div className="field"><label htmlFor="managers-detection-url">{t("Search API URL")}</label><input id="managers-detection-url" className="input" placeholder="https://indexer:9200" value={form.detection_url} onChange={(e) => set("detection_url", e.target.value)} /></div>
              <div className="field"><label htmlFor="managers-detection-user">{t("User name")}</label><input id="managers-detection-user" className="input" autoComplete="off" value={form.detection_username} onChange={(e) => set("detection_username", e.target.value)} placeholder={form.siem_type === "elastic" ? t("empty for an API key") : ""} /></div>
              <div className="field"><label htmlFor="managers-detection-secret">{t("Password or API key")}</label><input id="managers-detection-secret" className="input" type="password" autoComplete="new-password" value={form.detection_secret} onChange={(e) => set("detection_secret", e.target.value)} placeholder={editingManager?.has_detection_secret ? t("Stored — leave blank to keep") : ""} /></div>
            </div>
            {editingManager?.detection_configured && <DetectionTest manager={editingManager} onSaved={load} />}
          </fieldset>
        )}
        <div className="btn-group" style={{ marginTop: 12 }}>
          <button className="btn btn-primary" type="submit">{editing ? t("Update") : t("Create")}</button>
          {editing && <button className="btn btn-secondary" type="button" onClick={cancelEdit}>{t("Cancel")}</button>}
        </div>
      </form>

      <div className="card">
        {loading ? <Spinner /> : <DataTable columns={columns} rows={managers} emptyMsg={t("No SIEM targets. Add one above.")} />}
      </div>

      {viewData && (
        <Modal title={t("SIEM target: {name}", { name: viewData.name })} onClose={() => setViewData(null)}>
          <Details data={viewData} />
        </Modal>
      )}
    </>
  );
}
