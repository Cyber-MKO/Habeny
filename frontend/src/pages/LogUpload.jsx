import { useEffect, useState, useCallback } from "react";
import { api } from "../api";
import { useStore } from "../store";
import { PageHeader, DataTable, Pill, Spinner, JsonBlock } from "../components/UI";

const LOG_TYPES = ["auth", "web", "application", "system", "security", "custom"];

export default function LogUpload() {
  const { toast } = useStore();
  const [agents, setAgents] = useState([]);
  const [groups, setGroups] = useState([]);
  const [schedules, setSchedules] = useState([]);
  const [loading, setLoading] = useState(true);
  const [result, setResult] = useState(null);

  const [scope, setScope] = useState("container");
  const [mode, setMode] = useState("once");
  const [form, setForm] = useState({
    agent_id: "", group: "", destination_path: "/var/log/custom.log",
    log_type: "custom", append: true, content: "",
    interval_seconds: 120, duration_seconds: 600, indefinite: false,
  });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [a, g, s] = await Promise.all([
        api.getAgents({ limit: 1000 }),
        api.getGroups().catch(() => ({ data: { groups: [] } })),
        api.get("/agents/logs/schedules").catch(() => ({ data: { schedules: [] } })),
      ]);
      setAgents(a.data?.agents || []);
      setGroups(g.data?.groups || []);
      setSchedules(s.data?.schedules || []);
    } catch {}
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const set = (k, v) => setForm((p) => ({ ...p, [k]: v }));

  const handleUpload = async (e) => {
    e.preventDefault();
    const body = { content: form.content, destination_path: form.destination_path, log_type: form.log_type, append: form.append };
    try {
      let res;
      if (mode === "once") {
        if (scope === "container") {
          res = await api.uploadLogs(form.agent_id, body);
        } else {
          res = await api.post(`/groups/${form.group}/logs/upload`, body);
        }
      } else {
        const schedBody = { ...body, interval_seconds: Number(form.interval_seconds), duration_seconds: form.indefinite ? null : Number(form.duration_seconds), indefinite: form.indefinite };
        if (scope === "container") {
          res = await api.post(`/agents/${form.agent_id}/logs/schedule`, schedBody);
        } else {
          res = await api.post(`/groups/${form.group}/logs/schedule`, schedBody);
        }
      }
      setResult(res);
      toast(res.message || "Done", "success");
      load();
    } catch (err) { toast(err.message, "error"); }
  };

  const stopSchedule = async (id) => {
    try { await api.post(`/agents/logs/schedules/${id}/stop`); toast("Schedule stopped", "success"); load(); } catch (e) { toast(e.message, "error"); }
  };

  if (loading) return <Spinner />;

  return (
    <>
      <PageHeader title="Log Upload" subtitle="Upload or schedule log content to containers">
        <button className="btn btn-secondary" onClick={load}>Refresh</button>
      </PageHeader>

      <form onSubmit={handleUpload} className="card" style={{ marginBottom: 20 }}>
        <div className="form-grid">
          <div className="field">
            <label>Mode</label>
            <select className="select" value={mode} onChange={(e) => setMode(e.target.value)}>
              <option value="once">Send once</option>
              <option value="schedule">Send intermittently</option>
            </select>
          </div>
          <div className="field">
            <label>Scope</label>
            <select className="select" value={scope} onChange={(e) => setScope(e.target.value)}>
              <option value="container">Container</option>
              <option value="group">Group</option>
            </select>
          </div>
          {scope === "container" ? (
            <div className="field">
              <label>Container</label>
              <select className="select" value={form.agent_id} onChange={(e) => set("agent_id", e.target.value)} required>
                <option value="">— select —</option>
                {agents.map((a) => <option key={a.agent_name} value={a.agent_name}>{a.agent_name}{a.siem_type ? ` (${a.siem_type})` : ""}</option>)}
              </select>
              {(() => { const sel = agents.find((a) => a.agent_name === form.agent_id); return sel?.siem_type === "utmstack" ? <span style={{ fontSize: 11, color: "var(--cyan)", marginTop: 4 }}>UTMstack: filebeat config will be auto-updated to monitor the destination path</span> : null; })()}
            </div>
          ) : (
            <div className="field">
              <label>Group</label>
              <select className="select" value={form.group} onChange={(e) => set("group", e.target.value)} required>
                <option value="">— select —</option>
                {groups.map((g) => <option key={g.name} value={g.name}>{g.name}</option>)}
              </select>
            </div>
          )}
          <div className="field">
            <label>Destination Path</label>
            <input className="input" value={form.destination_path} onChange={(e) => set("destination_path", e.target.value)} required />
          </div>
          <div className="field">
            <label>Log Type</label>
            <select className="select" value={form.log_type} onChange={(e) => set("log_type", e.target.value)}>
              {LOG_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <div className="field">
            <label className="checkbox-label"><input type="checkbox" checked={form.append} onChange={(e) => set("append", e.target.checked)} /> Append</label>
          </div>
        </div>

        {mode === "schedule" && (
          <div className="form-grid" style={{ marginTop: 12 }}>
            <div className="field">
              <label>Interval (seconds)</label>
              <input className="input" type="number" min={5} value={form.interval_seconds} onChange={(e) => set("interval_seconds", e.target.value)} />
            </div>
            {!form.indefinite && (
              <div className="field">
                <label>Duration (seconds)</label>
                <input className="input" type="number" min={10} value={form.duration_seconds} onChange={(e) => set("duration_seconds", e.target.value)} />
              </div>
            )}
            <div className="field">
              <label className="checkbox-label"><input type="checkbox" checked={form.indefinite} onChange={(e) => set("indefinite", e.target.checked)} /> Run indefinitely</label>
            </div>
          </div>
        )}

        <div className="field" style={{ marginTop: 12 }}>
          <label>Log Content</label>
          <textarea className="textarea" value={form.content} onChange={(e) => set("content", e.target.value)} required />
        </div>
        <button className="btn btn-primary" type="submit" style={{ marginTop: 12 }}>{mode === "once" ? "Upload" : "Start Schedule"}</button>
      </form>

      {schedules.length > 0 && (
        <div className="card">
          <div className="section-title">Active Schedules</div>
          <DataTable
            columns={[
              { key: "schedule_id", label: "ID", render: (r) => (r.schedule_id || "").slice(0, 8) },
              { key: "agent_id", label: "Container" },
              { key: "status", label: "Status", render: (r) => <Pill status={r.status} /> },
              { key: "interval_seconds", label: "Interval" },
              { key: "runs", label: "Runs", render: (r) => r.runs ?? 0 },
              { key: "last_run", label: "Last Run", render: (r) => r.last_run || "—" },
              { key: "actions", label: "", render: (r) => r.status === "running" ? <button className="btn btn-sm btn-danger" onClick={() => stopSchedule(r.schedule_id)}>Stop</button> : null },
            ]}
            rows={schedules}
          />
        </div>
      )}

      {result && <div style={{ marginTop: 16 }}><JsonBlock data={result} /></div>}
    </>
  );
}
