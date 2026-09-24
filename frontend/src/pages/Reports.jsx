import { useState } from "react";
import { api } from "../api";
import { useStore } from "../store";
import { PageHeader, Spinner } from "../components/UI";
import { Details, RecordTable } from "../components/Details";
import { formatDateTime, t } from "../i18n";

// A generated report, readable: summary, findings and metrics
function ReportView({ report, fallback }) {
  if (!report) return <Details data={fallback} />;
  const { summary = {}, findings = [], metrics = {}, time_range: range } = report;
  return (
    <div className="report-view">
      <p className="account-help">
        {range && <>{t("From")} <time dateTime={range.start}>{formatDateTime(range.start)}</time> {t("to")}{" "}
          <time dateTime={range.end}>{formatDateTime(range.end)}</time>. </>}
        {t("Generated")} <time dateTime={report.generated_at}>{formatDateTime(report.generated_at)}</time>.
      </p>
      <h4 className="subsection-title">{t("Summary")}</h4>
      <Details data={{ ...summary, simulations_in_range: (summary.simulations_in_range || []).length }} />
      <h4 className="subsection-title">{t("Findings")}</h4>
      {findings.length
        ? (findings.every((f) => typeof f === "object") ? <RecordTable rows={findings} /> : <ul className="plain-list">{findings.map((f, i) => <li key={i}>{String(f)}</li>)}</ul>)
        : <p className="muted">{t("No findings.")}</p>}
      <h4 className="subsection-title">{t("Metrics")}</h4>
      <Details data={metrics} />
    </div>
  );
}

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
      toast(t("Report generated"), "success");
    } catch (e) { toast(e.message, "error"); }
    finally { setLoading(false); }
  };

  const handleFetch = async () => {
    if (!fetchId.trim()) return toast(t("Enter a report ID"), "error");
    setLoading(true);
    try { const res = await api.getReport(fetchId.trim()); setResult(res); toast(t("Report fetched"), "success"); }
    catch (e) { toast(e.message, "error"); }
    finally { setLoading(false); }
  };

  const reportId = result?.data?.report_id;

  return (
    <>
      <PageHeader title={t("Reports")} subtitle={t("Generate and retrieve reports")} />

      <form onSubmit={handleGenerate} className="card" style={{ marginBottom: 16 }}>
        <div className="section-title">{t("Generate Report")}</div>
        <div className="form-grid">
          <div className="field"><label htmlFor="reports-start-time">{t("Start Time")}</label><input id="reports-start-time" className="input" type="datetime-local" value={form.start_time} onChange={(e) => setForm((p) => ({ ...p, start_time: e.target.value }))} /></div>
          <div className="field"><label htmlFor="reports-end-time">{t("End Time")}</label><input id="reports-end-time" className="input" type="datetime-local" value={form.end_time} onChange={(e) => setForm((p) => ({ ...p, end_time: e.target.value }))} /></div>
          <div className="field"><label htmlFor="reports-format">{t("Format")}</label><select id="reports-format" className="select" value={form.format} onChange={(e) => setForm((p) => ({ ...p, format: e.target.value }))}><option value="json">JSON</option><option value="csv">CSV</option><option value="pdf">PDF</option></select></div>
          <div className="field"><label htmlFor="reports-metrics-comma-separated">{t("Metrics (comma-separated)")}</label><input id="reports-metrics-comma-separated" className="input" value={form.metrics} onChange={(e) => setForm((p) => ({ ...p, metrics: e.target.value }))} /></div>
          <div className="field"><label className="checkbox-label"><input type="checkbox" checked={form.include_findings} onChange={(e) => setForm((p) => ({ ...p, include_findings: e.target.checked }))} /> {t("Include findings")}</label></div>
          <div className="field" style={{ justifyContent: "flex-end" }}><button className="btn btn-primary" type="submit" disabled={loading}>{loading ? t("Generating…") : t("Generate")}</button></div>
        </div>
      </form>

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="section-title">{t("Fetch Report by ID")}</div>
        <div style={{ display: "flex", gap: 8 }}>
          <input className="input" placeholder={t("Report ID")} value={fetchId} onChange={(e) => setFetchId(e.target.value)} style={{ flex: 1 }} />
          <button className="btn btn-secondary" onClick={handleFetch} disabled={loading}>{t("Fetch")}</button>
        </div>
      </div>

      {history.length > 0 && (
        <div className="card" style={{ marginBottom: 16 }}>
          <div className="section-title">{t("Report History")}</div>
          <table>
            <thead><tr><th>{t("Report ID")}</th><th>{t("Actions")}</th></tr></thead>
            <tbody>
              {history.map((rid) => (
                <tr key={rid}>
                  <td style={{ fontFamily: "monospace", fontSize: 12 }}>{rid}</td>
                  <td>
                    <div className="btn-group">
                      <button className="btn btn-sm btn-secondary" onClick={() => { setFetchId(rid); handleFetch(); }}>{t("View")}</button>
                      <a className="btn btn-sm btn-secondary" href={api.reportDownloadUrl(rid, "json")} target="_blank" rel="noopener noreferrer">JSON</a>
                      <a className="btn btn-sm btn-secondary" href={api.reportDownloadUrl(rid, "csv")} target="_blank" rel="noopener noreferrer">CSV</a>
                      <a className="btn btn-sm btn-secondary" href={api.reportDownloadUrl(rid, "pdf")} target="_blank" rel="noopener noreferrer">PDF</a>
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
            <span>{t("Result")}</span>
            {reportId && <a className="btn btn-sm btn-secondary" href={api.reportDownloadUrl(reportId, form.format)} target="_blank" rel="noopener noreferrer">{t("Download")} {form.format.toUpperCase()}</a>}
          </div>
          <ReportView report={result.data?.report} fallback={result} />
        </div>
      )}
    </>
  );
}
