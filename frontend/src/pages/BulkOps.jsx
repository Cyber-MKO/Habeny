import { useEffect, useState, useCallback } from "react";
import { api } from "../api";
import { useStore } from "../store";
import { useConfirm } from "../components/Confirm";
import { PageHeader, Pill, Spinner } from "../components/UI";

const OPERATIONS = {
  start: { label: "Start", verb: "start", danger: false },
  stop: { label: "Stop", verb: "stop", danger: false },
  delete: { label: "Delete", verb: "delete", danger: true },
};

// What a bulk run did, per container, instead of the raw response
function BulkResult({ result, operation }) {
  const rows = result?.data?.results || [];
  const failed = rows.filter((r) => !r.success);
  return (
    <div className="card bulk-result" role="status">
      <div className="section-title">{result.message}</div>
      {failed.length > 0 && (
        <>
          <p className="account-help">{failed.length} couldn't {OPERATIONS[operation]?.verb || operation}:</p>
          <ul className="plain-list">
            {failed.map((r) => (
              <li key={r.agent_id}><strong>{r.agent_id}</strong>: {r.error || (operation === "start" ? "already running or didn't start" : operation === "stop" ? "not running or didn't stop" : "failed")}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

export default function BulkOps() {
  const { toast } = useStore();
  const confirm = useConfirm();
  const [agents, setAgents] = useState([]);
  const [groups, setGroups] = useState([]);
  const [selected, setSelected] = useState(new Set());
  const [loading, setLoading] = useState(true);
  const [operation, setOperation] = useState("start");
  const [groupName, setGroupName] = useState("");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);

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

  const toggle = (name) => setSelected((prev) => { const s = new Set(prev); if (s.has(name)) s.delete(name); else s.add(name); return s; });
  const selectAll = () => setSelected(new Set(agents.map((a) => a.agent_name)));
  const selectRunning = () => setSelected(new Set(agents.filter((a) => a.lifecycle_status === "running").map((a) => a.agent_name)));
  const clearSel = () => setSelected(new Set());

  const confirmRun = (count, target) => {
    const op = OPERATIONS[operation];
    return confirm({
      title: `${op.label} ${target}?`,
      message: operation === "delete"
        ? `${count === null ? "Every container in the group" : `${count} container${count === 1 ? "" : "s"}`} and everything in ${count === 1 ? "it" : "them"} will be destroyed. This can't be undone.`
        : `${op.label} ${count === null ? "every container in the group" : `${count} container${count === 1 ? "" : "s"}`}.`,
      confirmLabel: op.label,
      danger: op.danger,
      // Deleting many at once: make it deliberate
      requireText: operation === "delete" && (count === null || count > 5) ? "delete" : undefined,
    });
  };

  const run = async (fn) => {
    setBusy(true);
    try {
      const res = await fn();
      setResult({ ...res, operation });
      toast(res.message || "Done", res.success === false ? "error" : "success");
      load();
    } catch (e) { toast(e.message, "error"); }
    finally { setBusy(false); }
  };

  const runBulk = async () => {
    if (!selected.size) return toast("Select containers first", "error");
    if (!(await confirmRun(selected.size, `${selected.size} container${selected.size === 1 ? "" : "s"}`))) return;
    run(() => api.bulkOp(operation, { container_names: [...selected], operation }));
  };

  const runGroupBulk = async () => {
    if (!groupName) return toast("Select a group", "error");
    if (!(await confirmRun(null, `group ${groupName}`))) return;
    run(() => api.post(`/groups/${encodeURIComponent(groupName)}/bulk/${operation}`));
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
            <label htmlFor="bulk-operation">Operation</label>
            <select id="bulk-operation" className="select" value={operation} onChange={(e) => setOperation(e.target.value)}>
              {Object.entries(OPERATIONS).map(([value, op]) => <option key={value} value={value}>{op.label}</option>)}
            </select>
          </div>
          <div className="field">
            <label htmlFor="bulk-group">Target group (for group bulk)</label>
            <select id="bulk-group" className="select" value={groupName} onChange={(e) => setGroupName(e.target.value)}>
              <option value="">— select group —</option>
              {groups.map((g) => <option key={g.name} value={g.name}>{g.name}</option>)}
            </select>
          </div>
        </div>
        <div className="btn-group" style={{ marginTop: 12 }}>
          <button className={`btn ${OPERATIONS[operation].danger ? "btn-danger" : "btn-primary"}`} onClick={runBulk} disabled={busy || !selected.size}>
            {OPERATIONS[operation].label} selected ({selected.size})
          </button>
          <button className="btn btn-secondary" onClick={runGroupBulk} disabled={busy || !groupName}>{OPERATIONS[operation].label} group</button>
          <button className="btn btn-secondary btn-sm" onClick={selectAll}>Select all</button>
          <button className="btn btn-secondary btn-sm" onClick={selectRunning}>Select running</button>
          <button className="btn btn-secondary btn-sm" onClick={clearSel}>Clear</button>
        </div>
      </div>

      {result && <div style={{ marginBottom: 16 }}><BulkResult result={result} operation={result.operation} /></div>}

      <div className="card">
        <div className="table-wrap">
          <table>
            <caption className="sr-only">Containers to select for the bulk operation</caption>
            <thead>
              <tr>
                <th scope="col" style={{ width: 32 }}>
                  <input type="checkbox" aria-label="Select all containers" checked={selected.size === agents.length && agents.length > 0}
                    onChange={(e) => (e.target.checked ? selectAll() : clearSel())} />
                </th>
                <th scope="col">Name</th><th scope="col">Status</th><th scope="col">SIEM</th><th scope="col">Group</th><th scope="col">IP</th>
              </tr>
            </thead>
            <tbody>
              {agents.map((a) => (
                <tr key={a.agent_name} onClick={() => toggle(a.agent_name)} style={{ cursor: "pointer" }}>
                  <td>
                    <input type="checkbox" aria-label={`Select ${a.agent_name}`} checked={selected.has(a.agent_name)}
                      onChange={() => toggle(a.agent_name)} onClick={(e) => e.stopPropagation()} />
                  </td>
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
    </>
  );
}
