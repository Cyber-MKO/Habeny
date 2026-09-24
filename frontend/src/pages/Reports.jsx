import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { useStore } from "../store";
import { PageHeader, ScrollArea, Spinner } from "../components/UI";
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
  const [result, setResult] = useState(null);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(false);

  const loadHistory = useCallback(() => {
    api.getReports().then((res) => setHistory(res.data?.reports || [])).catch((e) => toast(e.message, "error"));
  }, [toast]);
  useEffect(() => { loadHistory(); }, [loadHistory]);


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
      loadHistory();
      toast(t("Report generated"), "success");
    } catch (e) { toast(e.message, "error"); }
    finally { setLoading(false); }
  };

  const handleView = async (rid) => {
    setLoading(true);
    try {
      const res = await api.getReport(rid);
      setResult({ data: { report_id: rid, report: res.data, format: "json" } });
    } catch (e) { toast(e.message, "error"); }
    finally { setLoading(false); }
  };

  const reportId = result?.data?.report_id;
  const resultFormat = result?.data?.format || "json";

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
        <div className="section-title">{t("Report History")}</div>
        {history.length === 0 ? <p className="muted">{t("No reports yet.")}</p> : (
          <ScrollArea label={t("Report History")}>
            <table>
              <thead><tr><th>{t("Generated")}</th><th>{t("Period")}</th><th>{t("Actions")}</th></tr></thead>
              <tbody>
                {history.map((r) => (
                  <tr key={r.report_id}>
                    <td>{r.generated_at ? <time dateTime={r.generated_at}>{formatDateTime(r.generated_at)}</time> : "—"}</td>
                    <td>{r.time_range ? `${formatDateTime(r.time_range.start)} – ${formatDateTime(r.time_range.end)}` : "—"}</td>
                    <td>
                      <div className="btn-group">
                        <button type="button" className="btn btn-sm btn-secondary" onClick={() => handleView(r.report_id)}>{t("View")}</button>
                        {r.formats.map((f) => (
                          <a key={f} className="btn btn-sm btn-secondary" href={api.reportDownloadUrl(r.report_id, f)} target="_blank" rel="noopener noreferrer">{f.toUpperCase()}</a>
                        ))}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </ScrollArea>
        )}
      </div>

      {loading && <Spinner />}
      {result && (
        <div className="card">
          <div className="section-title" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span>{t("Result")}</span>
            {reportId && <a className="btn btn-sm btn-secondary" href={api.reportDownloadUrl(reportId, resultFormat)} target="_blank" rel="noopener noreferrer">{t("Download")} {resultFormat.toUpperCase()}</a>}
          </div>
          <ReportView report={result.data?.report} fallback={result} />
        </div>
      )}
    </>
  );
}
