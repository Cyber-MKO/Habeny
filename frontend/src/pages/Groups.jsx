import { useEffect, useState, useCallback } from "react";
import { api } from "../api";
import { useStore } from "../store";
import { PageHeader, DataTable, Spinner, Modal, JsonBlock } from "../components/UI";

export default function Groups() {
  const { toast } = useStore();
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
      toast("Group created", "success");
      setNewName(""); setNewDesc("");
      load();
    } catch (e) { toast(e.message, "error"); }
  };

  const handleDelete = async (name) => {
    if (!confirm(`Delete group "${name}"?`)) return;
    try { await api.deleteGroup(name); toast("Group deleted", "success"); load(); } catch (e) { toast(e.message, "error"); }
  };

  const handleRename = async () => {
    try {
      await api.post(`/groups/${renameModal}/rename`, { new_name: renameForm.new_name, description: renameForm.description || null });
      toast("Group renamed", "success");
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
    if (!selectedAgents.size) return toast("Select agents", "error");
    try {
      await api.assignGroup(assignModal, { agent_ids: [...selectedAgents] });
      toast("Agents assigned", "success");
      setAssignModal(null);
      load();
    } catch (e) { toast(e.message, "error"); }
  };

  const handleRemoveFromGroup = async (groupName, agentIds) => {
    try {
      await api.removeGroup(groupName, { agent_ids: agentIds });
      toast("Agents removed from group", "success");
      load();
      openView(groupName);
    } catch (e) { toast(e.message, "error"); }
  };

  const columns = [
    { key: "name", label: "Name" },
    { key: "description", label: "Description", render: (r) => r.description || "—" },
    { key: "agent_count", label: "Agents", render: (r) => r.agent_count ?? 0 },
    { key: "created_at", label: "Created", render: (r) => r.created_at ? new Date(r.created_at).toLocaleString() : "—" },
    { key: "actions", label: "Actions", render: (r) => (
      <div className="btn-group">
        <button className="btn btn-sm btn-secondary" onClick={() => openView(r.name)}>View</button>
        <button className="btn btn-sm btn-secondary" onClick={() => openAssign(r.name)}>Assign</button>
        <button className="btn btn-sm btn-secondary" onClick={() => { setRenameModal(r.name); setRenameForm({ new_name: r.name, description: r.description || "" }); }}>Rename</button>
        <button className="btn btn-sm btn-danger" onClick={() => handleDelete(r.name)}>Delete</button>
      </div>
    )},
  ];

  return (
    <>
      <PageHeader title="Groups" subtitle="Organize containers into groups">
        <button className="btn btn-secondary" onClick={load}>Refresh</button>
      </PageHeader>

      <form onSubmit={handleCreate} className="card" style={{ marginBottom: 20 }}>
        <div className="section-title">Create Group</div>
        <div className="form-grid">
          <div className="field"><label>Name</label><input className="input" value={newName} onChange={(e) => setNewName(e.target.value)} required /></div>
          <div className="field"><label>Description</label><input className="input" value={newDesc} onChange={(e) => setNewDesc(e.target.value)} /></div>
          <div className="field" style={{ justifyContent: "flex-end" }}><button className="btn btn-primary" type="submit">Create</button></div>
        </div>
      </form>

      <div className="card">
        {loading ? <Spinner /> : <DataTable columns={columns} rows={groups} emptyMsg="No groups" />}
      </div>

      {renameModal && (
        <Modal title={`Rename: ${renameModal}`} onClose={() => setRenameModal(null)}>
          <div className="form-grid">
            <div className="field"><label>New Name</label><input className="input" value={renameForm.new_name} onChange={(e) => setRenameForm((p) => ({ ...p, new_name: e.target.value }))} /></div>
            <div className="field"><label>Description</label><input className="input" value={renameForm.description} onChange={(e) => setRenameForm((p) => ({ ...p, description: e.target.value }))} /></div>
          </div>
          <button className="btn btn-primary" style={{ marginTop: 12 }} onClick={handleRename}>Rename</button>
        </Modal>
      )}

      {viewModal && (
        <Modal title={`Containers in: ${viewModal}`} onClose={() => setViewModal(null)}>
          {viewAgents.length === 0 ? <div className="empty"><p>No containers in this group</p></div> : (
            <DataTable
              columns={[
                { key: "agent_name", label: "Name" },
                { key: "lifecycle_status", label: "Status", render: (r) => r.lifecycle_status || "—" },
                { key: "ip_addresses", label: "IP", render: (r) => r.ip_addresses?.[0] || "—" },
                { key: "rm", label: "", render: (r) => <button className="btn btn-sm btn-danger" onClick={() => handleRemoveFromGroup(viewModal, [r.agent_name])}>Remove</button> },
              ]}
              rows={viewAgents}
            />
          )}
        </Modal>
      )}

      {assignModal && (
        <Modal title={`Assign to: ${assignModal}`} onClose={() => setAssignModal(null)}>
          <div className="table-wrap" style={{ maxHeight: 350, overflowY: "auto" }}>
            <table>
              <thead><tr><th style={{ width: 32 }}></th><th>Name</th><th>Current Group</th></tr></thead>
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
          <button className="btn btn-primary" style={{ marginTop: 12 }} onClick={handleAssign}>Assign {selectedAgents.size} Agent{selectedAgents.size !== 1 ? "s" : ""}</button>
        </Modal>
      )}
    </>
  );
}
