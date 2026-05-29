import { useEffect, useState, useCallback } from "react";
import { api } from "../api";
import { useStore } from "../store";
import { PageHeader, Pill, Spinner, JsonBlock } from "../components/UI";

export default function BulkOps() {
  const { toast } = useStore();
  const [agents, setAgents] = useState([]);
  const [groups, setGroups] = useState([]);
  const [selected, setSelected] = useState(new Set());
  const [loading, setLoading] = useState(true);
  const [operation, setOperation] = useState("start");
  const [groupName, setGroupName] = useState("");
  const [result, setResult] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [a, g] = await Promise.all([api.getAgents({ limit: 1000 }), api.getGroups().catch(() => ({ data: { groups: [] } }))]);
      setAgents(a.data?.agents || []);
      setGroups(g.data?.groups || []);
    } catch (e) { toast(e.message, "error"); }
    finally { setLoading(false); }
  }, [toast]);

  useEffect(() => { load(); }, [load]);

  const toggle = (name) => setSelected((prev) => { const s = new Set(prev); s.has(name) ? s.delete(name) : s.add(name); return s; });
  const selectAll = () => setSelected(new Set(agents.map((a) => a.agent_name)));
  const selectRunning = () => setSelected(new Set(agents.filter((a) => a.lifecycle_status === "running").map((a) => a.agent_name)));
  const clearSel = () => setSelected(new Set());

  const runBulk = async () => {
    if (!selected.size) return toast("Select containers first", "error");
    try {
      const res = await api.bulkOp(operation, { container_names: [...selected], operation });
      setResult(res);
      toast(res.message || "Done", "success");
      load();
    } catch (e) { toast(e.message, "error"); }
  };

  const runGroupBulk = async () => {
    if (!groupName) return toast("Select a group", "error");
    try {
      const res = await api.post(`/groups/${groupName}/bulk/${operation}`);
      setResult(res);
      toast(res.message || "Done", "success");
      load();
    } catch (e) { toast(e.message, "error"); }
  };

  if (loading) return <Spinner />;

  return (
    <>
      <PageHeader title="Bulk Operations" subtitle={`${selected.size} selected`}>
        <button className="btn btn-secondary" onClick={load}>Refresh</button>
      </PageHeader>

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="form-grid">
          <div className="field">
            <label>Operation</label>
            <select className="select" value={operation} onChange={(e) => setOperation(e.target.value)}>
              <option value="start">Start</option>
              <option value="stop">Stop</option>
              <option value="delete">Delete</option>
            </select>
          </div>
          <div className="field">
            <label>Target Group (for group bulk)</label>
            <select className="select" value={groupName} onChange={(e) => setGroupName(e.target.value)}>
              <option value="">— select group —</option>
              {groups.map((g) => <option key={g.name} value={g.name}>{g.name}</option>)}
            </select>
          </div>
        </div>
        <div className="btn-group" style={{ marginTop: 12 }}>
          <button className="btn btn-primary" onClick={runBulk}>Run on Selected ({selected.size})</button>
          <button className="btn btn-secondary" onClick={runGroupBulk} disabled={!groupName}>Run for Group</button>
          <button className="btn btn-secondary btn-sm" onClick={selectAll}>Select All</button>
          <button className="btn btn-secondary btn-sm" onClick={selectRunning}>Select Running</button>
          <button className="btn btn-secondary btn-sm" onClick={clearSel}>Clear</button>
        </div>
      </div>

      <div className="card">
        <div className="table-wrap">
          <table>
            <thead><tr><th style={{width:32}}><input type="checkbox" checked={selected.size === agents.length && agents.length > 0} onChange={(e) => e.target.checked ? selectAll() : clearSel()} /></th><th>Name</th><th>Status</th><th>SIEM</th><th>Group</th><th>IP</th></tr></thead>
            <tbody>
              {agents.map((a) => (
                <tr key={a.agent_name} onClick={() => toggle(a.agent_name)} style={{ cursor: "pointer" }}>
                  <td><input type="checkbox" checked={selected.has(a.agent_name)} readOnly /></td>
                  <td>{a.agent_name}</td>
                  <td><Pill status={a.lifecycle_status} /></td>
                  <td>{a.siem_type || "—"}</td>
                  <td>{a.agent_group || "—"}</td>
                  <td>{a.ip_addresses?.[0] || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {result && <div style={{ marginTop: 16 }}><JsonBlock data={result} /></div>}
    </>
  );
}
