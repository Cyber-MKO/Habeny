import { useEffect, useState, useCallback } from "react";
import { api } from "../api";
import { useStore } from "../store";
import { PageHeader, DataTable, Spinner, Modal } from "../components/UI";
import { useConfirm } from "../components/Confirm";
import { formatDateTime, t } from "../i18n";

export default function Groups() {
  const { toast } = useStore();
  const confirm = useConfirm();
  const [groups, setGroups] = useState([]);
  const [agents, setAgents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");

  const [renameModal, setRenameModal] = useState(null);
  const [renameForm, setRenameForm] = useState({ new_name: "", description: "" });
  const [viewModal, setViewModal] = useState(null);
  const [viewAgents, setViewAgents] = useState([]);
  const [assignModal, setAssignModal] = useState(null);
  const [selectedAgents, setSelectedAgents] = useState(new Set());

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [g, a] = await Promise.all([api.getGroups(), api.getAgents({ limit: 1000 }).catch(() => ({ data: { agents: [] } }))]);
      setGroups(g.data?.groups || []);
      setAgents(a.data?.agents || []);
    } catch (e) { toast(e.message, "error"); }
    finally { setLoading(false); }
  }, [toast]);

  useEffect(() => { load(); }, [load]);

  const handleCreate = async (e) => {
    e.preventDefault();
    if (!newName.trim()) return;
    try {
      await api.createGroup({ name: newName.trim(), description: newDesc.trim() || null });
      toast(t("Group created"), "success");
      setNewName(""); setNewDesc("");
      load();
    } catch (e) { toast(e.message, "error"); }
  };

  const handleDelete = async (name) => {
    if (!(await confirm({ title: t("Delete group {name}?", { name }), message: t("Its containers stay; they're just no longer in this group."), confirmLabel: t("Delete group"), danger: true }))) return;
    try { await api.deleteGroup(name); toast(t("Group deleted"), "success"); load(); } catch (e) { toast(e.message, "error"); }
  };

  const handleRename = async () => {
    try {
      await api.post(`/groups/${renameModal}/rename`, { new_name: renameForm.new_name, description: renameForm.description || null });
      toast(t("Group renamed"), "success");
      setRenameModal(null);
      load();
    } catch (e) { toast(e.message, "error"); }
  };

  const openView = async (name) => {
    setViewModal(name);
    const list = agents.filter((a) => a.agent_group === name);
    setViewAgents(list);
  };

  const openAssign = (name) => {
    setAssignModal(name);
    setSelectedAgents(new Set());
  };

  const toggleAgent = (n) => setSelectedAgents((p) => { const s = new Set(p); s.has(n) ? s.delete(n) : s.add(n); return s; });

  const handleAssign = async () => {
    if (!selectedAgents.size) return toast(t("Select agents"), "error");
    try {
      await api.assignGroup(assignModal, { agent_ids: [...selectedAgents] });
      toast(t("Agents assigned"), "success");
      setAssignModal(null);
      load();
    } catch (e) { toast(e.message, "error"); }
  };

  const handleRemoveFromGroup = async (groupName, agentIds) => {
    try {
      await api.removeGroup(groupName, { agent_ids: agentIds });
      toast(t("Agents removed from group"), "success");
      load();
      openView(groupName);
    } catch (e) { toast(e.message, "error"); }
  };

  const columns = [
    { key: "name", label: t("Name") },
    { key: "description", label: t("Description"), render: (r) => r.description || "—" },
    { key: "agent_count", label: t("Agents"), render: (r) => r.agent_count ?? 0 },
    { key: "created_at", label: t("Created"), render: (r) => r.created_at ? formatDateTime(r.created_at) : "—" },
    { key: "actions", label: t("Actions"), render: (r) => (
      <div className="btn-group">
        <button className="btn btn-sm btn-secondary" onClick={() => openView(r.name)}>{t("View")}</button>
        <button className="btn btn-sm btn-secondary" onClick={() => openAssign(r.name)}>{t("Assign")}</button>
        <button className="btn btn-sm btn-secondary" onClick={() => { setRenameModal(r.name); setRenameForm({ new_name: r.name, description: r.description || "" }); }}>{t("Rename")}</button>
        <button className="btn btn-sm btn-danger" onClick={() => handleDelete(r.name)}>{t("Delete")}</button>
      </div>
    )},
  ];

  return (
    <>
      <PageHeader title={t("Groups")} subtitle={t("Organize containers into groups")}>
        <button className="btn btn-secondary" onClick={load}>{t("Refresh")}</button>
      </PageHeader>

      <form onSubmit={handleCreate} className="card" style={{ marginBottom: 20 }}>
        <div className="section-title">{t("Create Group")}</div>
        <div className="form-grid">
          <div className="field"><label htmlFor="groups-name">{t("Name")}</label><input id="groups-name" className="input" value={newName} onChange={(e) => setNewName(e.target.value)} required /></div>
          <div className="field"><label htmlFor="groups-description">{t("Description")}</label><input id="groups-description" className="input" value={newDesc} onChange={(e) => setNewDesc(e.target.value)} /></div>
          <div className="field" style={{ justifyContent: "flex-end" }}><button className="btn btn-primary" type="submit">{t("Create")}</button></div>
        </div>
      </form>

      <div className="card">
        {loading ? <Spinner /> : <DataTable columns={columns} rows={groups} emptyMsg={t("No groups")} />}
      </div>

      {renameModal && (
        <Modal title={t("Rename: {renameModal}", { renameModal })} onClose={() => setRenameModal(null)}>
          <div className="form-grid">
            <div className="field"><label htmlFor="groups-new-name">{t("New Name")}</label><input id="groups-new-name" className="input" value={renameForm.new_name} onChange={(e) => setRenameForm((p) => ({ ...p, new_name: e.target.value }))} /></div>
            <div className="field"><label htmlFor="groups-description-2">{t("Description")}</label><input id="groups-description-2" className="input" value={renameForm.description} onChange={(e) => setRenameForm((p) => ({ ...p, description: e.target.value }))} /></div>
          </div>
          <button className="btn btn-primary" style={{ marginTop: 12 }} onClick={handleRename}>{t("Rename")}</button>
        </Modal>
      )}

      {viewModal && (
        <Modal title={t("Containers in: {viewModal}", { viewModal })} onClose={() => setViewModal(null)}>
          {viewAgents.length === 0 ? <div className="empty"><p>{t("No containers in this group")}</p></div> : (
            <DataTable
              columns={[
                { key: "agent_name", label: t("Name") },
                { key: "lifecycle_status", label: t("Status"), render: (r) => r.lifecycle_status || "—" },
                { key: "ip_addresses", label: "IP", render: (r) => r.ip_addresses?.[0] || "—" },
                { key: "rm", label: "", render: (r) => <button className="btn btn-sm btn-danger" onClick={() => handleRemoveFromGroup(viewModal, [r.agent_name])}>{t("Remove")}</button> },
              ]}
              rows={viewAgents}
            />
          )}
        </Modal>
      )}

      {assignModal && (
        <Modal title={t("Assign to: {assignModal}", { assignModal })} onClose={() => setAssignModal(null)}>
          <div className="table-wrap" style={{ maxHeight: 350, overflowY: "auto" }}>
            <table>
              <thead><tr><th style={{ width: 32 }}></th><th>{t("Name")}</th><th>{t("Current Group")}</th></tr></thead>
              <tbody>
                {agents.map((a) => (
                  <tr key={a.agent_name} onClick={() => toggleAgent(a.agent_name)} style={{ cursor: "pointer" }}>
                    <td><input type="checkbox" checked={selectedAgents.has(a.agent_name)} readOnly /></td>
                    <td>{a.agent_name}</td>
                    <td>{a.agent_group || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <button className="btn btn-primary" style={{ marginTop: 12 }} onClick={handleAssign}>{selectedAgents.size === 1 ? t("Assign 1 container") : t("Assign {n} containers", { n: selectedAgents.size })}</button>
        </Modal>
      )}
    </>
  );
}
