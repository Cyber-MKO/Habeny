import { useEffect, useState, useCallback } from "react";
import { api } from "../api";
import { useStore } from "../store";
import { PageHeader, DataTable, Pill, Spinner } from "../components/UI";

const COLUMNS = [
  { key: "timestamp", label: "Time", render: (r) => r.timestamp ? new Date(r.timestamp).toLocaleString() : "—" },
  { key: "action", label: "Action" },
  { key: "status", label: "Status", render: (r) => <Pill status={r.status} /> },
  { key: "details", label: "Details", render: (r) => { const d = r.details || {}; return Object.entries(d).slice(0, 4).map(([k, v]) => `${k}: ${v}`).join(", ") || "—"; }},
];

export default function Activity() {
  const { toast } = useStore();
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("");
  const [limit, setLimit] = useState(100);
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = { limit, offset };
      if (filter) params.action = filter;
      const res = await api.getActivity(params);
      setLogs(res.data?.logs || []);
      setTotal(res.data?.total || 0);
    } catch (e) { toast(e.message, "error"); }
    finally { setLoading(false); }
  }, [limit, offset, filter, toast]);

  useEffect(() => { load(); }, [load]);

  return (
    <>
      <PageHeader title="Activity Log" subtitle={`${total} entries`}>
        <button className="btn btn-secondary" onClick={load}>Refresh</button>
      </PageHeader>

      <div className="filters">
        <div className="field"><label>Action</label><input className="input" placeholder="e.g. container_deployment_started" value={filter} onChange={(e) => { setFilter(e.target.value); setOffset(0); }} /></div>
        <div className="field"><label>Limit</label><input className="input" type="number" min={1} max={1000} value={limit} onChange={(e) => { setLimit(Number(e.target.value) || 100); setOffset(0); }} style={{ width: 80 }} /></div>
        <div className="field"><label>Offset</label><input className="input" type="number" min={0} value={offset} onChange={(e) => setOffset(Number(e.target.value) || 0)} style={{ width: 80 }} /></div>
        <div className="field" style={{ justifyContent: "flex-end" }}><button className="btn btn-secondary" onClick={load}>Apply</button></div>
      </div>

      <div className="card">
        {loading ? <Spinner /> : <DataTable columns={COLUMNS} rows={logs} emptyMsg="No activity logs" />}
      </div>

      {total > limit && (
        <div className="btn-group" style={{ marginTop: 16, justifyContent: "center" }}>
          <button className="btn btn-secondary btn-sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))}>Previous</button>
          <span style={{ padding: "6px 12px", color: "var(--text-dim)", fontSize: 13 }}>{offset + 1}–{Math.min(offset + limit, total)} of {total}</span>
          <button className="btn btn-secondary btn-sm" disabled={offset + limit >= total} onClick={() => setOffset(offset + limit)}>Next</button>
        </div>
      )}
    </>
  );
}
