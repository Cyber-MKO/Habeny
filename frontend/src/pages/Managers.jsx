import { useEffect, useState, useCallback } from "react";
import { api } from "../api";
import { useStore } from "../store";
import { PageHeader, DataTable, Pill, Spinner, Modal, JsonBlock } from "../components/UI";

const SIEM_TYPES = ["none", "wazuh", "ossec", "ossim", "utmstack", "elastic"];
const OS_TYPES = ["ubuntu_22_04", "ubuntu_20_04", "debian_11"];

const EMPTY_FORM = {
  name: "", description: "", siem_type: "wazuh", siem_ip: "", siem_version: "4.14.2",
  siem_auth_key: "", os_type: "ubuntu_22_04", agent_group: "default",
  memory_limit: "512MB", cpu_shares: 1024, config_template_id: "",
};

export default function Managers() {
  const { toast } = useStore();
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

  const handleSave = async (e) => {
    e.preventDefault();
    const payload = { ...form };
    payload.cpu_shares = Number(payload.cpu_shares);
    if (!payload.siem_ip && isBare) delete payload.siem_ip;
    if (!payload.siem_version || isBare || isUtm) delete payload.siem_version;
    if (!payload.siem_auth_key) delete payload.siem_auth_key;
    if (!payload.config_template_id) delete payload.config_template_id;
    if (!payload.description) delete payload.description;

    try {
      if (editing) {
        await api.updateManager(editing, payload);
        toast("Manager profile updated", "success");
        setEditing(null);
      } else {
        await api.createManager(payload);
        toast("Manager profile created", "success");
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
      siem_version: mgr.siem_version || "", siem_auth_key: mgr.siem_auth_key || "",
      os_type: mgr.os_type || "ubuntu_22_04", agent_group: mgr.agent_group || "default",
      memory_limit: mgr.memory_limit || "512MB", cpu_shares: mgr.cpu_shares || 1024,
      config_template_id: mgr.config_template_id || "",
    });
  };

  const handleDelete = async (id) => {
    if (!confirm("Delete this manager profile?")) return;
    try { await api.deleteManager(id); toast("Deleted", "success"); load(); }
    catch (e) { toast(e.message, "error"); }
  };

  const cancelEdit = () => { setEditing(null); setForm({ ...EMPTY_FORM }); };

  const columns = [
    { key: "name", label: "Name" },
    { key: "siem_type", label: "SIEM Type", render: (r) => <Pill status={r.siem_type === "none" ? "unknown" : r.siem_type} /> },
    { key: "siem_ip", label: "Manager IP", render: (r) => r.siem_ip || "—" },
    { key: "os_type", label: "OS" },
    { key: "agent_group", label: "Group" },
    { key: "memory_limit", label: "Memory" },
    { key: "created_at", label: "Created", render: (r) => r.created_at ? new Date(r.created_at).toLocaleDateString() : "—" },
    { key: "actions", label: "Actions", render: (r) => (
      <div className="btn-group">
        <button className="btn btn-sm btn-secondary" onClick={() => setViewData(r)}>View</button>
        <button className="btn btn-sm btn-secondary" onClick={() => handleEdit(r)}>Edit</button>
        <button className="btn btn-sm btn-danger" onClick={() => handleDelete(r.manager_id)}>Delete</button>
      </div>
    )},
  ];

  return (
    <>
      <PageHeader title="Managers" subtitle="Saved SIEM manager profiles for quick deployment">
        <button className="btn btn-secondary" onClick={load}>Refresh</button>
      </PageHeader>

      <form onSubmit={handleSave} className="card" style={{ marginBottom: 20 }}>
        <div className="section-title">{editing ? "Edit Profile" : "Create Profile"}</div>
        <div className="form-grid">
          <div className="field"><label>Profile Name</label><input className="input" value={form.name} onChange={(e) => set("name", e.target.value)} required /></div>
          <div className="field"><label>Description</label><input className="input" value={form.description} onChange={(e) => set("description", e.target.value)} /></div>
          <div className="field"><label>SIEM Type</label>
            <select className="select" value={form.siem_type} onChange={(e) => set("siem_type", e.target.value)}>
              {SIEM_TYPES.map((t) => <option key={t} value={t}>{t === "none" ? "None (bare)" : t.charAt(0).toUpperCase() + t.slice(1)}</option>)}
            </select>
          </div>
          {!isBare && <div className="field"><label>Manager IP / Hostname</label><input className="input" value={form.siem_ip} onChange={(e) => set("siem_ip", e.target.value)} /></div>}
          {!isBare && !needsAuthKey && <div className="field"><label>SIEM Version</label><input className="input" value={form.siem_version} onChange={(e) => set("siem_version", e.target.value)} /></div>}
          {isElastic && <div className="field"><label>Agent Version</label><input className="input" value={form.siem_version || "9.0.2"} onChange={(e) => set("siem_version", e.target.value)} /></div>}
          {needsAuthKey && <div className="field"><label>{isElastic ? "Enrollment Token" : "Auth Key"}</label><input className="input" value={form.siem_auth_key} onChange={(e) => set("siem_auth_key", e.target.value)} /></div>}
          <div className="field"><label>OS Type</label>
            <select className="select" value={form.os_type} onChange={(e) => set("os_type", e.target.value)}>
              {OS_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <div className="field"><label>Agent Group</label><input className="input" value={form.agent_group} onChange={(e) => set("agent_group", e.target.value)} /></div>
          <div className="field"><label>Memory Limit</label><input className="input" value={form.memory_limit} onChange={(e) => set("memory_limit", e.target.value)} /></div>
          <div className="field"><label>CPU Shares</label><input className="input" type="number" min={2} max={10240} value={form.cpu_shares} onChange={(e) => set("cpu_shares", e.target.value)} /></div>
          <div className="field"><label>Config Template ID</label><input className="input" value={form.config_template_id} onChange={(e) => set("config_template_id", e.target.value)} /></div>
        </div>
        <div className="btn-group" style={{ marginTop: 12 }}>
          <button className="btn btn-primary" type="submit">{editing ? "Update" : "Create"}</button>
          {editing && <button className="btn btn-secondary" type="button" onClick={cancelEdit}>Cancel</button>}
        </div>
      </form>

      <div className="card">
        {loading ? <Spinner /> : <DataTable columns={columns} rows={managers} emptyMsg="No manager profiles. Create one above." />}
      </div>

      {viewData && (
        <Modal title={`Manager: ${viewData.name}`} onClose={() => setViewData(null)}>
          <JsonBlock data={viewData} />
        </Modal>
      )}
    </>
  );
}
