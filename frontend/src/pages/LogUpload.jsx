import { useEffect, useState, useCallback } from "react";
import { api } from "../api";
import { useStore } from "../store";
import { PageHeader, DataTable, Pill, Spinner } from "../components/UI";
import { Details } from "../components/Details";
import { t } from "../i18n";

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
    } catch { /* agents, groups and schedules are optional here; the form still works */ }
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
      toast(res.message || t("Done"), "success");
      load();
    } catch (err) { toast(err.message, "error"); }
  };

  const stopSchedule = async (id) => {
    try { await api.post(`/agents/logs/schedules/${id}/stop`); toast(t("Schedule stopped"), "success"); load(); } catch (e) { toast(e.message, "error"); }
  };

  if (loading) return <Spinner />;

  return (
    <>
      <PageHeader title={t("Log Upload")} subtitle={t("Upload or schedule log content to containers")}>
        <button className="btn btn-secondary" onClick={load}>{t("Refresh")}</button>
      </PageHeader>

      <form onSubmit={handleUpload} className="card" style={{ marginBottom: 20 }}>
        <div className="form-grid">
          <div className="field">
            <label htmlFor="log-upload-mode">{t("Mode")}</label>
            <select id="log-upload-mode" className="select" value={mode} onChange={(e) => setMode(e.target.value)}>
              <option value="once">{t("Send once")}</option>
              <option value="schedule">{t("Send intermittently")}</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="log-upload-scope">{t("Scope")}</label>
            <select id="log-upload-scope" className="select" value={scope} onChange={(e) => setScope(e.target.value)}>
              <option value="container">{t("Container")}</option>
              <option value="group">{t("Group")}</option>
            </select>
          </div>
          {scope === "container" ? (
            <div className="field">
              <label htmlFor="log-upload-container">{t("Container")}</label>
              <select id="log-upload-container" className="select" value={form.agent_id} onChange={(e) => set("agent_id", e.target.value)} required>
                <option value="">{t("— select —")}</option>
                {agents.map((a) => <option key={a.agent_name} value={a.agent_name}>{a.agent_name}{a.siem_type ? ` (${a.siem_type})` : ""}</option>)}
              </select>
              {(() => { const sel = agents.find((a) => a.agent_name === form.agent_id); return sel?.siem_type === "utmstack" ? <span style={{ fontSize: 11, color: "var(--cyan)", marginTop: 4 }}>{t("UTMstack: filebeat config will be auto-updated to monitor the destination path")}</span> : null; })()}
            </div>
          ) : (
            <div className="field">
              <label htmlFor="log-upload-group">{t("Group")}</label>
              <select id="log-upload-group" className="select" value={form.group} onChange={(e) => set("group", e.target.value)} required>
                <option value="">{t("— select —")}</option>
                {groups.map((g) => <option key={g.name} value={g.name}>{g.name}</option>)}
              </select>
            </div>
          )}
          <div className="field">
            <label htmlFor="log-upload-destination-path">{t("Destination Path")}</label>
            <input id="log-upload-destination-path" className="input" value={form.destination_path} onChange={(e) => set("destination_path", e.target.value)} required />
          </div>
          <div className="field">
            <label htmlFor="log-upload-log-type">{t("Log Type")}</label>
            <select id="log-upload-log-type" className="select" value={form.log_type} onChange={(e) => set("log_type", e.target.value)}>
              {LOG_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <div className="field">
            <label className="checkbox-label"><input type="checkbox" checked={form.append} onChange={(e) => set("append", e.target.checked)} /> {t("Append")}</label>
          </div>
        </div>

        {mode === "schedule" && (
          <div className="form-grid" style={{ marginTop: 12 }}>
            <div className="field">
              <label htmlFor="log-upload-interval-seconds">{t("Interval (seconds)")}</label>
              <input id="log-upload-interval-seconds" className="input" type="number" min={5} value={form.interval_seconds} onChange={(e) => set("interval_seconds", e.target.value)} />
            </div>
            {!form.indefinite && (
              <div className="field">
                <label htmlFor="log-upload-duration-seconds">{t("Duration (seconds)")}</label>
                <input id="log-upload-duration-seconds" className="input" type="number" min={10} value={form.duration_seconds} onChange={(e) => set("duration_seconds", e.target.value)} />
              </div>
            )}
            <div className="field">
              <label className="checkbox-label"><input type="checkbox" checked={form.indefinite} onChange={(e) => set("indefinite", e.target.checked)} /> {t("Run indefinitely")}</label>
            </div>
          </div>
        )}

        <div className="field" style={{ marginTop: 12 }}>
          <label htmlFor="log-upload-log-content">{t("Log Content")}</label>
          <textarea id="log-upload-log-content" className="textarea" value={form.content} onChange={(e) => set("content", e.target.value)} required />
        </div>
        <button className="btn btn-primary" type="submit" style={{ marginTop: 12 }}>{mode === "once" ? t("Upload") : t("Start Schedule")}</button>
      </form>

      {schedules.length > 0 && (
        <div className="card">
          <div className="section-title">{t("Active Schedules")}</div>
          <DataTable
            columns={[
              { key: "schedule_id", label: "ID", render: (r) => (r.schedule_id || "").slice(0, 8) },
              { key: "agent_id", label: t("Container") },
              { key: "status", label: t("Status"), render: (r) => <Pill status={r.status} /> },
              { key: "interval_seconds", label: t("Interval") },
              { key: "runs", label: t("Runs"), render: (r) => r.runs ?? 0 },
              { key: "last_run", label: t("Last Run"), render: (r) => r.last_run || "—" },
              { key: "actions", label: "", render: (r) => r.status === "running" ? <button className="btn btn-sm btn-danger" onClick={() => stopSchedule(r.schedule_id)}>{t("Stop")}</button> : null },
            ]}
            rows={schedules}
          />
        </div>
      )}

      {result && (
        <div className="card result-card" role="status">
          <div className="section-title">{result.message}</div>
          {result.error && <div className="auth-error">{result.error}</div>}
          {result.data && <Details data={result.data} hide={["request"]} />}
        </div>
      )}
    </>
  );
}
