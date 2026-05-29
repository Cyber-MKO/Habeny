import { useState } from "react";
import { api } from "../api";
import { useStore } from "../store";
import { PageHeader, JsonBlock, Spinner } from "../components/UI";

export default function Reports() {
  const { toast } = useStore();
  const [form, setForm] = useState({
    start_time: new Date(Date.now() - 7 * 86400000).toISOString().slice(0, 16),
    end_time: new Date().toISOString().slice(0, 16),
    format: "json", metrics: "all", include_findings: true,
  });
  const [fetchId, setFetchId] = useState("");
  const [result, setResult] = useState(null);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(false);

  const BASE = import.meta.env.VITE_API_URL || "/api";

  const handleGenerate = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const metrics = form.metrics.split(",").map((m) => m.trim()).filter(Boolean);
      const res = await api.generateReport({
        start_time: new Date(form.start_time).toISOString(),
        end_time: new Date(form.end_time).toISOString(),
        format: form.format, include_findings: form.include_findings, metrics,
      });
      setResult(res);
      const rid = res.data?.report_id;
      if (rid && !history.includes(rid)) setHistory((p) => [rid, ...p]);
      toast("Report generated", "success");
    } catch (e) { toast(e.message, "error"); }
    finally { setLoading(false); }
  };

  const handleFetch = async () => {
    if (!fetchId.trim()) return toast("Enter a report ID", "error");
    setLoading(true);
    try { const res = await api.getReport(fetchId.trim()); setResult(res); toast("Report fetched", "success"); }
    catch (e) { toast(e.message, "error"); }
    finally { setLoading(false); }
  };

  const reportId = result?.data?.report_id;

  return (
    <>
      <PageHeader title="Reports" subtitle="Generate and retrieve reports" />

      <form onSubmit={handleGenerate} className="card" style={{ marginBottom: 16 }}>
        <div className="section-title">Generate Report</div>
        <div className="form-grid">
          <div className="field"><label>Start Time</label><input className="input" type="datetime-local" value={form.start_time} onChange={(e) => setForm((p) => ({ ...p, start_time: e.target.value }))} /></div>
          <div className="field"><label>End Time</label><input className="input" type="datetime-local" value={form.end_time} onChange={(e) => setForm((p) => ({ ...p, end_time: e.target.value }))} /></div>
          <div className="field"><label>Format</label><select className="select" value={form.format} onChange={(e) => setForm((p) => ({ ...p, format: e.target.value }))}><option value="json">JSON</option><option value="csv">CSV</option><option value="pdf">PDF</option></select></div>
          <div className="field"><label>Metrics (comma-separated)</label><input className="input" value={form.metrics} onChange={(e) => setForm((p) => ({ ...p, metrics: e.target.value }))} /></div>
          <div className="field"><label className="checkbox-label"><input type="checkbox" checked={form.include_findings} onChange={(e) => setForm((p) => ({ ...p, include_findings: e.target.checked }))} /> Include findings</label></div>
          <div className="field" style={{ justifyContent: "flex-end" }}><button className="btn btn-primary" type="submit" disabled={loading}>{loading ? "Generating…" : "Generate"}</button></div>
        </div>
      </form>

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="section-title">Fetch Report by ID</div>
        <div style={{ display: "flex", gap: 8 }}>
          <input className="input" placeholder="Report ID" value={fetchId} onChange={(e) => setFetchId(e.target.value)} style={{ flex: 1 }} />
          <button className="btn btn-secondary" onClick={handleFetch} disabled={loading}>Fetch</button>
        </div>
      </div>

      {history.length > 0 && (
        <div className="card" style={{ marginBottom: 16 }}>
          <div className="section-title">Report History</div>
          <table>
            <thead><tr><th>Report ID</th><th>Actions</th></tr></thead>
            <tbody>
              {history.map((rid) => (
                <tr key={rid}>
                  <td style={{ fontFamily: "monospace", fontSize: 12 }}>{rid}</td>
                  <td>
                    <div className="btn-group">
                      <button className="btn btn-sm btn-secondary" onClick={() => { setFetchId(rid); handleFetch(); }}>View</button>
                      <a className="btn btn-sm btn-secondary" href={`${BASE}/reports/${rid}/download?format=json`} target="_blank" rel="noopener noreferrer">JSON</a>
                      <a className="btn btn-sm btn-secondary" href={`${BASE}/reports/${rid}/download?format=csv`} target="_blank" rel="noopener noreferrer">CSV</a>
                      <a className="btn btn-sm btn-secondary" href={`${BASE}/reports/${rid}/download?format=pdf`} target="_blank" rel="noopener noreferrer">PDF</a>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {loading && <Spinner />}
      {result && (
        <div className="card">
          <div className="section-title" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span>Result</span>
            {reportId && <a className="btn btn-sm btn-secondary" href={`${BASE}/reports/${reportId}/download?format=${form.format}`} target="_blank" rel="noopener noreferrer">Download {form.format.toUpperCase()}</a>}
          </div>
          <JsonBlock data={result.data?.report || result} />
        </div>
      )}
    </>
  );
}
