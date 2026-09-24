import { useEffect, useState, useCallback } from "react";
import { api } from "../api";
import { useStore } from "../store";
import { PageHeader, DataTable, Spinner, Modal } from "../components/UI";
import { Details } from "../components/Details";
import { formatDateTime, t } from "../i18n";

export default function Configs() {
  const { toast } = useStore();
  const [configs, setConfigs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState({ name: "", siem_type: "wazuh", content: "", description: "", version: "", tags: "" });
  const [exportData, setExportData] = useState(null);

  const load = useCallback(async () => {
    try { const res = await api.getConfigs(); setConfigs(res.data?.templates || []); }
    catch (e) { toast(e.message, "error"); }
    finally { setLoading(false); }
  }, [toast]);

  useEffect(() => { load(); }, [load]);

  const handleImport = async (e) => {
    e.preventDefault();
    try {
      const tags = form.tags ? form.tags.split(",").map((t) => t.trim()).filter(Boolean) : [];
      await api.importConfig({ name: form.name, siem_type: form.siem_type, content: form.content, description: form.description || null, version: form.version || null, tags });
      toast(t("Config imported"), "success");
      setForm({ name: "", siem_type: "wazuh", content: "", description: "", version: "", tags: "" });
      load();
    } catch (e) { toast(e.message, "error"); }
  };

  const handleExport = async (id) => {
    try { const res = await api.exportConfig(id); setExportData(res.data); }
    catch (e) { toast(e.message, "error"); }
  };

  const columns = [
    { key: "template_id", label: "ID", render: (r) => (r.template_id || "").slice(0, 8) + "…" },
    { key: "name", label: t("Name") },
    { key: "siem_type", label: "SIEM" },
    { key: "version", label: t("Version"), render: (r) => r.version || "—" },
    { key: "description", label: t("Description"), render: (r) => r.description || "—" },
    { key: "tags", label: t("Tags"), render: (r) => (r.tags || []).join(", ") || "—" },
    { key: "created_at", label: t("Created"), render: (r) => r.created_at ? formatDateTime(r.created_at) : "—" },
    { key: "actions", label: "", render: (r) => <button className="btn btn-sm btn-secondary" onClick={() => handleExport(r.template_id)}>{t("Export")}</button> },
  ];

  return (
    <>
      <PageHeader title={t("Configs")} subtitle={t("Configuration templates")}>
        <button className="btn btn-secondary" onClick={load}>{t("Refresh")}</button>
      </PageHeader>

      <form onSubmit={handleImport} className="card" style={{ marginBottom: 20 }}>
        <div className="section-title">{t("Import Template")}</div>
        <div className="form-grid">
          <div className="field"><label htmlFor="configs-name">{t("Name")}</label><input id="configs-name" className="input" value={form.name} onChange={(e) => setForm((p) => ({ ...p, name: e.target.value }))} required /></div>
          <div className="field"><label htmlFor="configs-siem-type">{t("SIEM Type")}</label><select id="configs-siem-type" className="select" value={form.siem_type} onChange={(e) => setForm((p) => ({ ...p, siem_type: e.target.value }))}><option value="wazuh">Wazuh</option><option value="ossec">OSSEC</option><option value="utmstack">UTMstack</option><option value="elastic">Elastic</option></select></div>
          <div className="field"><label htmlFor="configs-version">{t("Version")}</label><input id="configs-version" className="input" value={form.version} onChange={(e) => setForm((p) => ({ ...p, version: e.target.value }))} placeholder="1.0" /></div>
          <div className="field"><label htmlFor="configs-tags-comma-separated">{t("Tags (comma-separated)")}</label><input id="configs-tags-comma-separated" className="input" value={form.tags} onChange={(e) => setForm((p) => ({ ...p, tags: e.target.value }))} placeholder={t("production, high-security")} /></div>
          <div className="field"><label htmlFor="configs-description">{t("Description")}</label><input id="configs-description" className="input" value={form.description} onChange={(e) => setForm((p) => ({ ...p, description: e.target.value }))} /></div>
        </div>
        <div className="field" style={{ marginTop: 12 }}><label htmlFor="configs-content">{t("Content")}</label><textarea id="configs-content" className="textarea" value={form.content} onChange={(e) => setForm((p) => ({ ...p, content: e.target.value }))} required /></div>
        <button className="btn btn-primary" type="submit" style={{ marginTop: 12 }}>{t("Import")}</button>
      </form>

      <div className="card">{loading ? <Spinner /> : <DataTable columns={columns} rows={configs} emptyMsg={t("No config templates")} />}</div>

      {exportData && (
        <Modal title={t("Config Template")} onClose={() => setExportData(null)}>
          <Details data={exportData.data || exportData} />
        </Modal>
      )}
    </>
  );
}
