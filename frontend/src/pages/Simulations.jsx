import { useEffect, useState, useCallback } from "react";
import { api } from "../api";
import { useMetricsSocket } from "../ws";
import { useStore } from "../store";
import { PageHeader, DataTable, Pill, Spinner, JsonBlock } from "../components/UI";

const SIM_COLUMNS = [
  { key: "simulation_id", label: "ID", render: (r) => (r.simulation_id || "").slice(0, 8) + "…" },
  { key: "profile_id", label: "Profile" },
  { key: "status", label: "Status", render: (r) => <Pill status={r.status} /> },
  { key: "target_agents", label: "Targets", render: (r) => r.target_agents?.length ?? 0 },
  { key: "eps_target", label: "EPS" },
  { key: "duration", label: "Duration (s)" },
  { key: "events_generated", label: "Events", render: (r) => (r.events_generated ?? 0).toLocaleString() },
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
    file_path: "/var/log/custom-eps.json", message: "Custom EPS log event",
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
    try { await api.stopSimulation(id); toast("Stopped", "success"); load(); } catch (e) { toast(e.message, "error"); }
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
      if (form.custom_parameters.trim()) try { cp = JSON.parse(form.custom_parameters); } catch { return toast("Invalid custom_parameters JSON", "error"); }
      const res = await api.startSimulation({
        profile_id: form.profile_id, agent_selector: buildSelector(form),
        duration: Number(form.duration), eps_target: Number(form.eps_target),
        intensity: form.intensity, burst_mode: form.burst_mode, custom_parameters: cp,
      });
      setResult(res); toast("Simulation started", "success"); load();
    } catch (e) { toast(e.message, "error"); }
  };

  const handleCustom = async (e) => {
    e.preventDefault();
    try {
      let extra = {};
      if (customForm.extra_fields.trim()) try { extra = JSON.parse(customForm.extra_fields); } catch { return toast("Invalid extra_fields JSON", "error"); }
      const res = await api.loadSimulation({
        agent_selector: buildSelector(customForm),
        file_path: customForm.file_path, message: customForm.message,
        src_ip: customForm.src_ip, dest_ip: customForm.dest_ip,
        duration: Number(customForm.duration), eps: Number(customForm.eps),
        seq_start: Number(customForm.seq_start),
        start_time: customForm.start_time || null, extra_fields: extra,
      });
      setResult(res); toast("Custom simulation started", "success"); load();
    } catch (e) { toast(e.message, "error"); }
  };

  const handleSyslog = async (e) => {
    e.preventDefault();
    try {
      const res = await api.startSyslog({ ...sysForm, eps: Number(sysForm.eps), duration: Number(sysForm.duration), target_port: Number(sysForm.target_port), device_count: Number(sysForm.device_count), facility: Number(sysForm.facility) });
      setResult(res); toast("Syslog simulation started", "success"); load();
    } catch (e) { toast(e.message, "error"); }
  };

  const SelectorFields = ({ f, setF }) => (
    <div className="form-grid" style={{ marginTop: 12, borderTop: "1px solid var(--border)", paddingTop: 12 }}>
      <div className="section-title" style={{ gridColumn: "1/-1", margin: 0 }}>Agent Selector</div>
      <div className="field"><label>Count</label><input className="input" type="number" value={f.sel_count} onChange={(e) => setF((p) => ({ ...p, sel_count: e.target.value }))} /></div>
      <div className="field"><label>SIEM</label><select className="select" value={f.sel_siem} onChange={(e) => setF((p) => ({ ...p, sel_siem: e.target.value }))}><option value="">Any</option><option value="wazuh">Wazuh</option><option value="ossec">OSSEC</option><option value="ossim">OSSIM</option><option value="utmstack">UTMstack</option><option value="elastic">Elastic</option></select></div>
      <div className="field"><label>Group</label><input className="input" value={f.sel_group} onChange={(e) => setF((p) => ({ ...p, sel_group: e.target.value }))} /></div>
      <div className="field"><label>Agent IDs (comma-separated)</label><input className="input" value={f.sel_ids || ""} onChange={(e) => setF((p) => ({ ...p, sel_ids: e.target.value }))} /></div>
    </div>
  );

  const cols = [...SIM_COLUMNS, { key: "actions", label: "", render: (r) => r.status === "running" ? <button className="btn btn-sm btn-danger" onClick={() => handleStop(r.simulation_id)}>Stop</button> : null }];

  return (
    <>
      <PageHeader title="Simulations" subtitle="Attack, custom log, and syslog simulations">
        <button className="btn btn-secondary" onClick={load}>Refresh</button>
      </PageHeader>

      <div className="btn-group" style={{ marginBottom: 16 }}>
        {["attack", "custom", "syslog"].map((t) => (
          <button key={t} className={`btn ${tab === t ? "btn-primary" : "btn-secondary"}`} onClick={() => setTab(t)}>{t === "attack" ? "Attack" : t === "custom" ? "Custom EPS" : "Syslog"}</button>
        ))}
      </div>

      {tab === "attack" && (
        <form onSubmit={handleAttack} className="card" style={{ marginBottom: 20 }}>
          <div className="section-title">Attack Simulation</div>
          <div className="form-grid">
            <div className="field"><label>Profile</label><select className="select" value={form.profile_id} onChange={(e) => setForm((p) => ({ ...p, profile_id: e.target.value }))}>{PROFILES.map((p) => <option key={p} value={p}>{p}</option>)}</select></div>
            <div className="field"><label>Duration (s)</label><input className="input" type="number" value={form.duration} onChange={(e) => setForm((p) => ({ ...p, duration: e.target.value }))} /></div>
            <div className="field"><label>EPS Target</label><input className="input" type="number" value={form.eps_target} onChange={(e) => setForm((p) => ({ ...p, eps_target: e.target.value }))} /></div>
            <div className="field"><label>Intensity</label><select className="select" value={form.intensity} onChange={(e) => setForm((p) => ({ ...p, intensity: e.target.value }))}><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option></select></div>
            <div className="field"><label className="checkbox-label"><input type="checkbox" checked={form.burst_mode} onChange={(e) => setForm((p) => ({ ...p, burst_mode: e.target.checked }))} /> Burst mode</label></div>
            <div className="field"><label>Custom Parameters (JSON)</label><input className="input" value={form.custom_parameters} onChange={(e) => setForm((p) => ({ ...p, custom_parameters: e.target.value }))} placeholder='{}' /></div>
          </div>
          <SelectorFields f={form} setF={setForm} />
          <button className="btn btn-primary" type="submit" style={{ marginTop: 12 }}>Start Simulation</button>
        </form>
      )}

      {tab === "custom" && (
        <form onSubmit={handleCustom} className="card" style={{ marginBottom: 20 }}>
          <div className="section-title">Custom EPS Log Simulation</div>
          <div className="form-grid">
            <div className="field"><label>EPS</label><input className="input" type="number" value={customForm.eps} onChange={(e) => setCustomForm((p) => ({ ...p, eps: e.target.value }))} /></div>
            <div className="field"><label>Duration (s)</label><input className="input" type="number" value={customForm.duration} onChange={(e) => setCustomForm((p) => ({ ...p, duration: e.target.value }))} /></div>
            <div className="field"><label>File Path</label><input className="input" value={customForm.file_path} onChange={(e) => setCustomForm((p) => ({ ...p, file_path: e.target.value }))} /></div>
            <div className="field"><label>Message</label><input className="input" value={customForm.message} onChange={(e) => setCustomForm((p) => ({ ...p, message: e.target.value }))} /></div>
            <div className="field"><label>Source IP</label><input className="input" value={customForm.src_ip} onChange={(e) => setCustomForm((p) => ({ ...p, src_ip: e.target.value }))} /></div>
            <div className="field"><label>Dest IP</label><input className="input" value={customForm.dest_ip} onChange={(e) => setCustomForm((p) => ({ ...p, dest_ip: e.target.value }))} /></div>
            <div className="field"><label>Seq Start</label><input className="input" type="number" value={customForm.seq_start} onChange={(e) => setCustomForm((p) => ({ ...p, seq_start: e.target.value }))} /></div>
            <div className="field"><label>Start Time (optional)</label><input className="input" type="datetime-local" value={customForm.start_time} onChange={(e) => setCustomForm((p) => ({ ...p, start_time: e.target.value }))} /></div>
            <div className="field"><label>Extra Fields (JSON)</label><input className="input" value={customForm.extra_fields} onChange={(e) => setCustomForm((p) => ({ ...p, extra_fields: e.target.value }))} placeholder='{"severity":"info"}' /></div>
          </div>
          <SelectorFields f={customForm} setF={setCustomForm} />
          <button className="btn btn-primary" type="submit" style={{ marginTop: 12 }}>Start Custom Simulation</button>
        </form>
      )}

      {tab === "syslog" && (
        <form onSubmit={handleSyslog} className="card" style={{ marginBottom: 20 }}>
          <div className="section-title">Syslog Simulation</div>
          <div className="form-grid">
            <div className="field" style={{ gridColumn: "1 / -1" }}>
              <label>Use Syslog Config Profile</label>
              <select className="select" onChange={(e) => {
                const cfg = syslogConfigs.find((x) => x.config_id === e.target.value);
                if (cfg) setSysForm((p) => ({ ...p, target_ip: cfg.target_ip, target_port: cfg.target_port || 514, protocol: cfg.protocol || "tcp" }));
                if (!cfg) { const m = managers.find((x) => x.manager_id === e.target.value); if (m?.siem_ip) setSysForm((p) => ({ ...p, target_ip: m.siem_ip })); }
              }}>
                <option value="">— select to auto-fill —</option>
                {syslogConfigs.map((c) => <option key={c.config_id} value={c.config_id}>{c.name} ({c.target_ip}:{c.target_port} {(c.protocol||"tcp").toUpperCase()})</option>)}
                {managers.filter((m) => m.siem_ip).map((m) => <option key={m.manager_id} value={m.manager_id}>[Manager] {m.name} ({m.siem_ip})</option>)}
              </select>
            </div>
            <div className="field"><label>Target IP</label><input className="input" value={sysForm.target_ip} onChange={(e) => setSysForm((p) => ({ ...p, target_ip: e.target.value }))} required /></div>
            <div className="field"><label>Port</label><input className="input" type="number" value={sysForm.target_port} onChange={(e) => setSysForm((p) => ({ ...p, target_port: e.target.value }))} /></div>
            <div className="field"><label>Protocol</label><select className="select" value={sysForm.protocol} onChange={(e) => setSysForm((p) => ({ ...p, protocol: e.target.value }))}><option value="tcp">TCP</option><option value="udp">UDP</option></select></div>
            <div className="field"><label>EPS</label><input className="input" type="number" value={sysForm.eps} onChange={(e) => setSysForm((p) => ({ ...p, eps: e.target.value }))} /></div>
            <div className="field"><label>Duration (s)</label><input className="input" type="number" value={sysForm.duration} onChange={(e) => setSysForm((p) => ({ ...p, duration: e.target.value }))} /></div>
            <div className="field"><label>Devices</label><input className="input" type="number" value={sysForm.device_count} onChange={(e) => setSysForm((p) => ({ ...p, device_count: e.target.value }))} /></div>
            <div className="field"><label>Device Prefix</label><input className="input" value={sysForm.device_name_prefix} onChange={(e) => setSysForm((p) => ({ ...p, device_name_prefix: e.target.value }))} /></div>
            <div className="field"><label>Device Type</label><select className="select" value={sysForm.device_type} onChange={(e) => setSysForm((p) => ({ ...p, device_type: e.target.value }))}><option value="mixed">Mixed</option><option value="router">Router</option><option value="switch">Switch</option><option value="firewall">Firewall</option><option value="ids">IDS</option></select></div>
            <div className="field"><label>Facility</label><input className="input" type="number" min={0} max={23} value={sysForm.facility} onChange={(e) => setSysForm((p) => ({ ...p, facility: e.target.value }))} /></div>
          </div>
          <button className="btn btn-primary" type="submit" style={{ marginTop: 12 }}>Start Syslog</button>
        </form>
      )}

      <div className="card">
        <div className="section-title">All Simulations</div>
        {loading ? <Spinner /> : <DataTable columns={cols} rows={sims} emptyMsg="No simulations" />}
      </div>

      {result && <div style={{ marginTop: 16 }}><JsonBlock data={result} /></div>}
    </>
  );
}
