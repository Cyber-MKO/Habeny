import { useEffect, useState, useCallback } from "react";
import { api } from "../api";
import { useMetricsSocket } from "../ws";
import { useStore } from "../store";
import { PageHeader, DataTable, Pill, Spinner, Modal } from "../components/UI";
import Terminal from "../components/Terminal";
import { useConfirm } from "../components/Confirm";
import { Details } from "../components/Details";
import { t } from "../i18n";

const COLUMNS = [
  { key: "agent_name", label: t("Name") },
  { key: "siem_type", label: "SIEM", render: (r) => r.siem_type || "—" },
  { key: "lifecycle_status", label: t("Status"), render: (r) => <Pill status={r.lifecycle_status} /> },
  { key: "siem_agent_status", label: t("Agent Svc"), render: (r) => r.siem_agent_running === true ? <Pill status="running" /> : r.siem_agent_running === false ? <Pill status="stopped" /> : <span style={{ color: "var(--text-muted)" }}>—</span> },
  { key: "manager_status", label: t("Manager"), render: (r) => r.manager_reachable === true ? <><Pill status="connected" /> <span style={{ fontSize: 11, color: "var(--text-muted)" }}>{r.manager_host ? `${r.manager_host}:${r.manager_port || ""}` : ""}</span></> : r.manager_reachable === false ? <Pill status="disconnected" /> : <span style={{ color: "var(--text-muted)" }}>—</span> },
  { key: "ip_addresses", label: "IP", render: (r) => r.ip_addresses?.[0] || "—" },
  { key: "agent_group", label: t("Group"), render: (r) => r.agent_group || "—" },
];

// UTMstack only: its agent can listen for syslog on port 7014, a destination for syslog simulations
function UtmSyslogListener({ agent, onChanged }) {
  const { toast } = useStore();
  const [protocol, setProtocol] = useState("tcp");
  const [busy, setBusy] = useState(false);
  const on = agent.syslog_listener;
  const change = async (enable) => {
    setBusy(true);
    try {
      const res = await (enable ? api.enableUtmSyslog : api.disableUtmSyslog)(agent.agent_name, enable ? protocol : on);
      toast(res.message, res.success ? "success" : "error");
      if (res.success) onChanged();
    } catch (e) { toast(e.message, "error"); }
    finally { setBusy(false); }
  };
  return (
    <fieldset className="detection-fields">
      <legend>{t("Syslog listener (port 7014)")}</legend>
      <p className="auth-hint">
        {on ? t("Listening for syslog on {address} over {protocol}. Syslog simulations can send to it.", { address: `${agent.ip_addresses?.[0] || agent.agent_name}:7014`, protocol: on.toUpperCase() })
          : t("Off. Turn it on to send syslog simulations to this container's UTMstack agent.")}
      </p>
      <div className="btn-group">
        {on ? <button className="btn btn-sm btn-danger" onClick={() => change(false)} disabled={busy}>{t("Turn off")}</button> : (
          <>
            <label className="sr-only" htmlFor="utm-syslog-protocol">{t("Protocol")}</label>
            <select id="utm-syslog-protocol" className="select" style={{ width: "auto" }} value={protocol} onChange={(e) => setProtocol(e.target.value)} disabled={busy}>
              <option value="tcp">TCP</option><option value="udp">UDP</option>
            </select>
            <button className="btn btn-sm btn-primary" onClick={() => change(true)} disabled={busy}>{t("Turn on")}</button>
          </>
        )}
      </div>
    </fieldset>
  );
}

export default function Agents() {
  const { toast } = useStore();
  const confirm = useConfirm();
  const { metrics } = useMetricsSocket();
  const [agents, setAgents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState({ siem_type: "", status: "", agent_group: "", limit: 100, offset: 0 });
  const [total, setTotal] = useState(0);
  const [detail, setDetail] = useState(null);
  const [detailData, setDetailData] = useState(null);
  const [groups, setGroups] = useState([]);
  const [consoleName, setConsoleName] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = {};
      if (filters.siem_type) params.siem_type = filters.siem_type;
      if (filters.status) params.status = filters.status;
      if (filters.agent_group) params.agent_group = filters.agent_group;
      params.limit = filters.limit;
      params.offset = filters.offset;
      const [res, g] = await Promise.all([
        api.getAgents(params),
        api.getGroups().catch(() => ({ data: { groups: [] } })),
      ]);
      setAgents(res.data?.agents || []);
      setTotal(res.data?.total || 0);
      setGroups(g.data?.groups || []);
    } catch (e) { toast(e.message, "error"); }
    finally { setLoading(false); }
  }, [filters, toast]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (metrics?.agents_changed) load(); }, [metrics?.agents_changed, load]);

  const setFilter = (k, v) => setFilters((p) => ({ ...p, [k]: v, offset: 0 }));

  const showDetail = async (agent) => {
    setDetail(agent.agent_name);
    try {
      const res = await api.getAgent(agent.agent_name);
      setDetailData(res.data);
    } catch { setDetailData(agent); }
  };

  const action = async (fn, label) => {
    try { await fn(); toast(t("{label} succeeded", { label }), "success"); load(); } catch (e) { toast(e.message, "error"); }
  };

  const actionsCol = {
    key: "actions", label: t("Actions"),
    render: (r) => (
      <div className="btn-group">
        <button className="btn btn-sm btn-secondary" onClick={(e) => { e.stopPropagation(); showDetail(r); }}>{t("Details")}</button>
        {r.lifecycle_status === "running" && (
          <button className="btn btn-sm btn-secondary" onClick={(e) => { e.stopPropagation(); setConsoleName(r.agent_name); }}>{t("Console")}</button>
        )}
        {r.lifecycle_status === "running"
          ? <button className="btn btn-sm btn-secondary" onClick={(e) => { e.stopPropagation(); action(() => api.stopAgent(r.agent_name), "Stop"); }}>{t("Stop")}</button>
          : <button className="btn btn-sm btn-primary" onClick={(e) => { e.stopPropagation(); action(() => api.startAgent(r.agent_name), "Start"); }}>{t("Start")}</button>
        }
        <button className="btn btn-sm btn-danger" aria-label={t("Delete {agent_name}", { agent_name: r.agent_name })} onClick={async (e) => {
          e.stopPropagation();
          if (await confirm({ title: t("Delete {agent_name}?", { agent_name: r.agent_name }), message: t("The container and everything in it is destroyed. This can't be undone."), confirmLabel: t("Delete container"), danger: true })) {
            action(() => api.deleteAgent(r.agent_name), "Delete");
          }
        }}>{t("Delete")}</button>
      </div>
    ),
  };

  return (
    <>
      <PageHeader title={t("Containers")} subtitle={t("{total} containers", { total })}>
        <button className="btn btn-secondary" onClick={load}>{t("Refresh")}</button>
      </PageHeader>

      <div className="filters">
        <div className="field">
          <label htmlFor="agents-siem-type">{t("SIEM Type")}</label>
          <select id="agents-siem-type" className="select" value={filters.siem_type} onChange={(e) => setFilter("siem_type", e.target.value)}>
            <option value="">{t("All")}</option>
            <option value="none">{t("None")}</option>
            <option value="wazuh">Wazuh</option>
            <option value="ossec">OSSEC</option>
            <option value="utmstack">UTMstack</option>
            <option value="elastic">Elastic</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="agents-status">{t("Status")}</label>
          <select id="agents-status" className="select" value={filters.status} onChange={(e) => setFilter("status", e.target.value)}>
            <option value="">{t("All")}</option>
            <option value="running">{t("Running")}</option>
            <option value="stopped">{t("Stopped")}</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="agents-group">{t("Group")}</label>
          <select id="agents-group" className="select" value={filters.agent_group} onChange={(e) => setFilter("agent_group", e.target.value)}>
            <option value="">{t("All")}</option>
            {groups.map((g) => <option key={g.name} value={g.name}>{g.name}</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor="agents-limit">{t("Limit")}</label>
          <input id="agents-limit" className="input" type="number" min={1} max={1000} value={filters.limit} onChange={(e) => setFilter("limit", Number(e.target.value) || 100)} style={{ width: 80 }} />
        </div>
      </div>

      <div className="card">
        {loading ? <Spinner /> : <DataTable columns={[...COLUMNS, actionsCol]} rows={agents} emptyMsg={t("No containers found")} />}
      </div>

      {total > filters.limit && (
        <div className="btn-group" style={{ marginTop: 16, justifyContent: "center" }}>
          <button className="btn btn-secondary btn-sm" disabled={filters.offset === 0} onClick={() => setFilters((p) => ({ ...p, offset: Math.max(0, p.offset - p.limit) }))}>{t("Previous")}</button>
          <span style={{ padding: "6px 12px", color: "var(--text-dim)", fontSize: 13 }}>{filters.offset + 1}–{Math.min(filters.offset + filters.limit, total)} {t("of")} {total}</span>
          <button className="btn btn-secondary btn-sm" disabled={filters.offset + filters.limit >= total} onClick={() => setFilters((p) => ({ ...p, offset: p.offset + p.limit }))}>{t("Next")}</button>
        </div>
      )}

      {detail && (
        <Modal title={t("Container: {detail}", { detail })} onClose={() => { setDetail(null); setDetailData(null); }}>
          {detailData ? <Details data={detailData} /> : <Spinner />}
          {detailData?.siem_type === "utmstack" && detailData.lifecycle_status === "running" && (
            <UtmSyslogListener agent={detailData} onChanged={() => showDetail(detailData)} />
          )}
          <div className="btn-group" style={{ marginTop: 12 }}>
            <button className="btn btn-sm btn-primary" onClick={() => { setDetail(null); setDetailData(null); setConsoleName(detail); }}>{t("Open Console")}</button>
          </div>
        </Modal>
      )}

      {consoleName && (
        <Terminal containerName={consoleName} onClose={() => setConsoleName(null)} />
      )}
    </>
  );
}
