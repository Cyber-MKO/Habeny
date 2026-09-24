import { useEffect, useState, useCallback } from "react";
import { api } from "../api";
import { useMetricsSocket } from "../ws";
import { useStore } from "../store";
import { PageHeader, DataTable, Pill, Spinner } from "../components/UI";
import { Details } from "../components/Details";
import { t } from "../i18n";

const SIM_COLUMNS = [
  { key: "simulation_id", label: "ID", render: (r) => (r.simulation_id || "").slice(0, 8) + "…" },
  { key: "profile_id", label: t("Profile") },
  { key: "status", label: t("Status"), render: (r) => <Pill status={r.status} /> },
  { key: "target_agents", label: t("Targets"), render: (r) => r.target_agents?.length ?? 0 },
  { key: "eps_target", label: "EPS" },
  { key: "duration", label: t("Duration (s)") },
  { key: "events_generated", label: t("Events"), render: (r) => (r.events_generated ?? 0).toLocaleString() },
];

const PROFILES = ["auth_bruteforce", "web_attacks", "malware_beacon", "lateral_movement", "privilege_escalation", "port_scan"];

export default function Simulations() {
  const { toast } = useStore();
  const { metrics } = useMetricsSocket();
  const [sims, setSims] = useState([]);
  const [managers, setManagers] = useState([]);
  const [syslogConfigs, setSyslogConfigs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [result, setResult] = useState(null);
  const [tab, setTab] = useState("attack");

  useEffect(() => {
    api.getManagers().then((r) => setManagers(r.data?.managers || [])).catch(() => {});
    api.getSyslogConfigs().then((r) => setSyslogConfigs(r.data?.configs || [])).catch(() => {});
  }, []);

  const [form, setForm] = useState({
    profile_id: "auth_bruteforce", duration: 300, eps_target: 100, intensity: "medium", burst_mode: false, custom_parameters: "",
    sel_count: 10, sel_siem: "", sel_group: "", sel_ids: "",
  });
  const [sysForm, setSysForm] = useState({
    target_ip: "", target_port: 514, protocol: "tcp", eps: 100,
    duration: 300, device_count: 4, device_type: "mixed", device_name_prefix: "device", facility: 1,
  });
  const [customForm, setCustomForm] = useState({
    file_path: "/var/log/custom-eps.json", message: t("Custom EPS log event"),
    src_ip: "192.168.1.100", dest_ip: "10.0.0.1", duration: 300, eps: 100,
    seq_start: 1, start_time: "", extra_fields: "",
    sel_count: 10, sel_siem: "", sel_group: "",
  });

  const load = useCallback(async () => {
    try { const res = await api.getSimulations(); setSims(res.data?.simulations || []); }
    catch (e) { toast(e.message, "error"); }
    finally { setLoading(false); }
  }, [toast]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (metrics?.simulations_changed) load(); }, [metrics?.simulations_changed, load]);

  const handleStop = async (id) => {
    try { await api.stopSimulation(id); toast(t("Stopped"), "success"); load(); } catch (e) { toast(e.message, "error"); }
  };

  const buildSelector = (f) => {
    const s = {};
    if (f.sel_count) s.count = Number(f.sel_count);
    if (f.sel_siem) s.siem_type = f.sel_siem;
    if (f.sel_group) s.agent_group = f.sel_group;
    if (f.sel_ids) s.agent_ids = f.sel_ids.split(",").map((x) => x.trim()).filter(Boolean);
    return s;
  };

  const handleAttack = async (e) => {
    e.preventDefault();
    try {
      let cp = {};
      if (form.custom_parameters.trim()) try { cp = JSON.parse(form.custom_parameters); } catch { return toast(t("Invalid custom_parameters JSON"), "error"); }
      const res = await api.startSimulation({
        profile_id: form.profile_id, agent_selector: buildSelector(form),
        duration: Number(form.duration), eps_target: Number(form.eps_target),
        intensity: form.intensity, burst_mode: form.burst_mode, custom_parameters: cp,
      });
      setResult(res); toast(t("Simulation started"), "success"); load();
    } catch (e) { toast(e.message, "error"); }
  };

  const handleCustom = async (e) => {
    e.preventDefault();
    try {
      let extra = {};
      if (customForm.extra_fields.trim()) try { extra = JSON.parse(customForm.extra_fields); } catch { return toast(t("Invalid extra_fields JSON"), "error"); }
      const res = await api.loadSimulation({
        agent_selector: buildSelector(customForm),
        file_path: customForm.file_path, message: customForm.message,
        src_ip: customForm.src_ip, dest_ip: customForm.dest_ip,
        duration: Number(customForm.duration), eps: Number(customForm.eps),
        seq_start: Number(customForm.seq_start),
        start_time: customForm.start_time || null, extra_fields: extra,
      });
      setResult(res); toast(t("Custom simulation started"), "success"); load();
    } catch (e) { toast(e.message, "error"); }
  };

  const handleSyslog = async (e) => {
    e.preventDefault();
    try {
      const res = await api.startSyslog({ ...sysForm, eps: Number(sysForm.eps), duration: Number(sysForm.duration), target_port: Number(sysForm.target_port), device_count: Number(sysForm.device_count), facility: Number(sysForm.facility) });
      setResult(res); toast(t("Syslog simulation started"), "success"); load();
    } catch (e) { toast(e.message, "error"); }
  };

  const SelectorFields = ({ f, setF }) => (
    <div className="form-grid" style={{ marginTop: 12, borderTop: "1px solid var(--border)", paddingTop: 12 }}>
      <div className="section-title" style={{ gridColumn: "1/-1", margin: 0 }}>{t("Agent Selector")}</div>
      <div className="field"><label htmlFor="simulations-count">{t("Count")}</label><input id="simulations-count" className="input" type="number" value={f.sel_count} onChange={(e) => setF((p) => ({ ...p, sel_count: e.target.value }))} /></div>
      <div className="field"><label htmlFor="simulations-siem">SIEM</label><select id="simulations-siem" className="select" value={f.sel_siem} onChange={(e) => setF((p) => ({ ...p, sel_siem: e.target.value }))}><option value="">{t("Any")}</option><option value="wazuh">Wazuh</option><option value="ossec">OSSEC</option><option value="utmstack">UTMstack</option><option value="elastic">Elastic</option></select></div>
      <div className="field"><label htmlFor="simulations-group">{t("Group")}</label><input id="simulations-group" className="input" value={f.sel_group} onChange={(e) => setF((p) => ({ ...p, sel_group: e.target.value }))} /></div>
      <div className="field"><label htmlFor="simulations-agent-ids-comma-separated">{t("Agent IDs (comma-separated)")}</label><input id="simulations-agent-ids-comma-separated" className="input" value={f.sel_ids || ""} onChange={(e) => setF((p) => ({ ...p, sel_ids: e.target.value }))} /></div>
    </div>
  );

  const cols = [...SIM_COLUMNS, { key: "actions", label: "", render: (r) => r.status === "running" ? <button className="btn btn-sm btn-danger" onClick={() => handleStop(r.simulation_id)}>{t("Stop")}</button> : null }];

  return (
    <>
      <PageHeader title={t("Simulations")} subtitle={t("Attack, custom log, and syslog simulations")}>
        <button className="btn btn-secondary" onClick={load}>{t("Refresh")}</button>
      </PageHeader>

      <div className="btn-group" style={{ marginBottom: 16 }}>
        {["attack", "custom", "syslog"].map((name) => (
          <button key={name} className={`btn ${tab === name ? "btn-primary" : "btn-secondary"}`} onClick={() => setTab(name)}>{name === "attack" ? t("Attack") : name === "custom" ? t("Custom EPS") : t("Syslog")}</button>
        ))}
      </div>

      {tab === "attack" && (
        <form onSubmit={handleAttack} className="card" style={{ marginBottom: 20 }}>
          <div className="section-title">{t("Attack Simulation")}</div>
          <div className="form-grid">
            <div className="field"><label htmlFor="simulations-profile">{t("Profile")}</label><select id="simulations-profile" className="select" value={form.profile_id} onChange={(e) => setForm((p) => ({ ...p, profile_id: e.target.value }))}>{PROFILES.map((p) => <option key={p} value={p}>{p}</option>)}</select></div>
            <div className="field"><label htmlFor="simulations-duration-s">{t("Duration (s)")}</label><input id="simulations-duration-s" className="input" type="number" value={form.duration} onChange={(e) => setForm((p) => ({ ...p, duration: e.target.value }))} /></div>
            <div className="field"><label htmlFor="simulations-eps-target">{t("EPS Target")}</label><input id="simulations-eps-target" className="input" type="number" value={form.eps_target} onChange={(e) => setForm((p) => ({ ...p, eps_target: e.target.value }))} /></div>
            <div className="field"><label htmlFor="simulations-intensity">{t("Intensity")}</label><select id="simulations-intensity" className="select" value={form.intensity} onChange={(e) => setForm((p) => ({ ...p, intensity: e.target.value }))}><option value="low">{t("Low")}</option><option value="medium">{t("Medium")}</option><option value="high">{t("High")}</option></select></div>
            <div className="field"><label className="checkbox-label"><input type="checkbox" checked={form.burst_mode} onChange={(e) => setForm((p) => ({ ...p, burst_mode: e.target.checked }))} /> {t("Burst mode")}</label></div>
            <div className="field"><label htmlFor="simulations-custom-parameters-json">{t("Custom Parameters (JSON)")}</label><input id="simulations-custom-parameters-json" className="input" value={form.custom_parameters} onChange={(e) => setForm((p) => ({ ...p, custom_parameters: e.target.value }))} placeholder='{}' /></div>
          </div>
          <SelectorFields f={form} setF={setForm} />
          <button className="btn btn-primary" type="submit" style={{ marginTop: 12 }}>{t("Start Simulation")}</button>
        </form>
      )}

      {tab === "custom" && (
        <form onSubmit={handleCustom} className="card" style={{ marginBottom: 20 }}>
          <div className="section-title">{t("Custom EPS Log Simulation")}</div>
          <div className="form-grid">
            <div className="field"><label htmlFor="simulations-eps">EPS</label><input id="simulations-eps" className="input" type="number" value={customForm.eps} onChange={(e) => setCustomForm((p) => ({ ...p, eps: e.target.value }))} /></div>
            <div className="field"><label htmlFor="simulations-duration-s-2">{t("Duration (s)")}</label><input id="simulations-duration-s-2" className="input" type="number" value={customForm.duration} onChange={(e) => setCustomForm((p) => ({ ...p, duration: e.target.value }))} /></div>
            <div className="field"><label htmlFor="simulations-file-path">{t("File Path")}</label><input id="simulations-file-path" className="input" value={customForm.file_path} onChange={(e) => setCustomForm((p) => ({ ...p, file_path: e.target.value }))} /></div>
            <div className="field"><label htmlFor="simulations-message">{t("Message")}</label><input id="simulations-message" className="input" value={customForm.message} onChange={(e) => setCustomForm((p) => ({ ...p, message: e.target.value }))} /></div>
            <div className="field"><label htmlFor="simulations-source-ip">{t("Source IP")}</label><input id="simulations-source-ip" className="input" value={customForm.src_ip} onChange={(e) => setCustomForm((p) => ({ ...p, src_ip: e.target.value }))} /></div>
            <div className="field"><label htmlFor="simulations-dest-ip">{t("Dest IP")}</label><input id="simulations-dest-ip" className="input" value={customForm.dest_ip} onChange={(e) => setCustomForm((p) => ({ ...p, dest_ip: e.target.value }))} /></div>
            <div className="field"><label htmlFor="simulations-seq-start">{t("Seq Start")}</label><input id="simulations-seq-start" className="input" type="number" value={customForm.seq_start} onChange={(e) => setCustomForm((p) => ({ ...p, seq_start: e.target.value }))} /></div>
            <div className="field"><label htmlFor="simulations-start-time-optional">{t("Start Time (optional)")}</label><input id="simulations-start-time-optional" className="input" type="datetime-local" value={customForm.start_time} onChange={(e) => setCustomForm((p) => ({ ...p, start_time: e.target.value }))} /></div>
            <div className="field"><label htmlFor="simulations-extra-fields-json">{t("Extra Fields (JSON)")}</label><input id="simulations-extra-fields-json" className="input" value={customForm.extra_fields} onChange={(e) => setCustomForm((p) => ({ ...p, extra_fields: e.target.value }))} placeholder={t("{\"severity\":\"info\"}")} /></div>
          </div>
          <SelectorFields f={customForm} setF={setCustomForm} />
          <button className="btn btn-primary" type="submit" style={{ marginTop: 12 }}>{t("Start Custom Simulation")}</button>
        </form>
      )}

      {tab === "syslog" && (
        <form onSubmit={handleSyslog} className="card" style={{ marginBottom: 20 }}>
          <div className="section-title">{t("Syslog Simulation")}</div>
          <div className="form-grid">
            <div className="field" style={{ gridColumn: "1 / -1" }}>
              <label htmlFor="simulations-use-syslog-config-profile">{t("Use Syslog Config Profile")}</label>
              <select id="simulations-use-syslog-config-profile" className="select" onChange={(e) => {
                const cfg = syslogConfigs.find((x) => x.config_id === e.target.value);
                if (cfg) setSysForm((p) => ({ ...p, target_ip: cfg.target_ip, target_port: cfg.target_port || 514, protocol: cfg.protocol || "tcp" }));
                if (!cfg) { const m = managers.find((x) => x.manager_id === e.target.value); if (m?.siem_ip) setSysForm((p) => ({ ...p, target_ip: m.siem_ip })); }
              }}>
                <option value="">{t("— select to auto-fill —")}</option>
                {syslogConfigs.map((c) => <option key={c.config_id} value={c.config_id}>{c.name} ({c.target_ip}:{c.target_port} {(c.protocol||"tcp").toUpperCase()})</option>)}
                {managers.filter((m) => m.siem_ip).map((m) => <option key={m.manager_id} value={m.manager_id}>{t("[Manager]")} {m.name} ({m.siem_ip})</option>)}
              </select>
            </div>
            <div className="field"><label htmlFor="simulations-target-ip">{t("Target IP")}</label><input id="simulations-target-ip" className="input" value={sysForm.target_ip} onChange={(e) => setSysForm((p) => ({ ...p, target_ip: e.target.value }))} required /></div>
            <div className="field"><label htmlFor="simulations-port">{t("Port")}</label><input id="simulations-port" className="input" type="number" value={sysForm.target_port} onChange={(e) => setSysForm((p) => ({ ...p, target_port: e.target.value }))} /></div>
            <div className="field"><label htmlFor="simulations-protocol">{t("Protocol")}</label><select id="simulations-protocol" className="select" value={sysForm.protocol} onChange={(e) => setSysForm((p) => ({ ...p, protocol: e.target.value }))}><option value="tcp">TCP</option><option value="udp">UDP</option></select></div>
            <div className="field"><label htmlFor="simulations-eps-2">EPS</label><input id="simulations-eps-2" className="input" type="number" value={sysForm.eps} onChange={(e) => setSysForm((p) => ({ ...p, eps: e.target.value }))} /></div>
            <div className="field"><label htmlFor="simulations-duration-s-3">{t("Duration (s)")}</label><input id="simulations-duration-s-3" className="input" type="number" value={sysForm.duration} onChange={(e) => setSysForm((p) => ({ ...p, duration: e.target.value }))} /></div>
            <div className="field"><label htmlFor="simulations-devices">{t("Devices")}</label><input id="simulations-devices" className="input" type="number" value={sysForm.device_count} onChange={(e) => setSysForm((p) => ({ ...p, device_count: e.target.value }))} /></div>
            <div className="field"><label htmlFor="simulations-device-prefix">{t("Device Prefix")}</label><input id="simulations-device-prefix" className="input" value={sysForm.device_name_prefix} onChange={(e) => setSysForm((p) => ({ ...p, device_name_prefix: e.target.value }))} /></div>
            <div className="field"><label htmlFor="simulations-device-type">{t("Device Type")}</label><select id="simulations-device-type" className="select" value={sysForm.device_type} onChange={(e) => setSysForm((p) => ({ ...p, device_type: e.target.value }))}><option value="mixed">{t("Mixed")}</option><option value="router">{t("Router")}</option><option value="switch">{t("Switch")}</option><option value="firewall">{t("Firewall")}</option><option value="ids">IDS</option></select></div>
            <div className="field"><label htmlFor="simulations-facility">{t("Facility")}</label><input id="simulations-facility" className="input" type="number" min={0} max={23} value={sysForm.facility} onChange={(e) => setSysForm((p) => ({ ...p, facility: e.target.value }))} /></div>
          </div>
          <button className="btn btn-primary" type="submit" style={{ marginTop: 12 }}>{t("Start Syslog")}</button>
        </form>
      )}

      <div className="card">
        <div className="section-title">{t("All Simulations")}</div>
        {loading ? <Spinner /> : <DataTable columns={cols} rows={sims} emptyMsg={t("No simulations")} />}
      </div>

      {result && (
        <div className="card result-card" role="status">
          <div className="section-title">{result.message}</div>
          {result.error && <div className="auth-error">{result.error}</div>}
          {result.data && (
            <Details data={{
              ...result.data,
              target_agents: Array.isArray(result.data.target_agents) ? `${result.data.target_agents.length} (${result.data.target_agents.slice(0, 5).join(", ")}${result.data.target_agents.length > 5 ? ", …" : ""})` : result.data.target_agents,
            }} hide={["custom_parameters"]} />
          )}
        </div>
      )}
    </>
  );
}
