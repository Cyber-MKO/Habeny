import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { useStore } from "../store";
import { useConfirm } from "../components/Confirm";
import { DataTable, Modal, PageHeader, Pill, Spinner } from "../components/UI";

const TYPES = [
  { value: "slack", label: "Slack", help: "An incoming-webhook URL from Slack (or a Slack-compatible chat such as Mattermost)." },
  { value: "webhook", label: "Webhook", help: "Habeny POSTs JSON to your URL. With a secret, each request is signed (X-Habeny-Signature)." },
  { value: "email", label: "Email", help: "Sent through the mail server set in the configuration (HABENY_SMTP_*)." },
];

const EVENT_SHORT = {
  "deployment.finished": "Deployments", "simulation.finished": "Simulations", "benchmark.finished": "Benchmarks",
  "alert.firing": "Alerts", "alert.resolved": "Alerts cleared",
};

const EMPTY = { name: "", type: "slack", url: "", secret: "", to: "", events: [], only_problems: false, enabled: true };

function ChannelModal({ channel, events, emailAvailable, onClose, onSaved }) {
  const { toast } = useStore();
  const editing = Boolean(channel);
  const [form, setForm] = useState(() => (channel ? {
    ...EMPTY, name: channel.name, type: channel.type, events: channel.events,
    only_problems: channel.only_problems, enabled: channel.enabled,
    to: (channel.config.to || []).join(", "),
  } : EMPTY));
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));
  const toggleEvent = (name) => setForm((f) => ({
    ...f, events: f.events.includes(name) ? f.events.filter((e) => e !== name) : [...f.events, name],
  }));

  const submit = async (e) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    const config = form.type === "email" ? { to: form.to } : { url: form.url, ...(form.type === "webhook" ? { secret: form.secret } : {}) };
    const body = { name: form.name.trim(), type: form.type, config, events: form.events, only_problems: form.only_problems, enabled: form.enabled };
    try {
      const res = editing ? await api.updateChannel(channel.id, body) : await api.createChannel(body);
      toast(res.message, "success");
      onSaved();
      onClose();
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  };

  const type = TYPES.find((t) => t.value === form.type);
  return (
    <Modal title={editing ? `Edit ${channel.name}` : "New notification channel"} onClose={onClose}>
      <form className="account-modal-form" onSubmit={submit} noValidate>
        {error && <div className="auth-error" role="alert">{error}</div>}
        <div className="field">
          <label htmlFor="ch-name">Name</label>
          <input id="ch-name" className="input" value={form.name} onChange={set("name")} maxLength={64} placeholder="e.g. #soc-alerts" />
        </div>
        <fieldset className="field" disabled={editing}>
          <legend>Type</legend>
          <div className="radio-row">
            {TYPES.map((t) => (
              <label key={t.value} className="checkbox-inline">
                <input type="radio" name="ch-type" value={t.value} checked={form.type === t.value} onChange={set("type")}
                  disabled={t.value === "email" && !emailAvailable} /> {t.label}
              </label>
            ))}
          </div>
          <span className="auth-hint">
            {type.help}
            {form.type === "email" && !emailAvailable && " Email is off until HABENY_SMTP_HOST is set."}
          </span>
        </fieldset>
        {form.type === "email" ? (
          <div className="field">
            <label htmlFor="ch-to">Send to</label>
            <input id="ch-to" className="input" value={form.to} onChange={set("to")} placeholder="soc@example.com, oncall@example.com" />
          </div>
        ) : (
          <div className="field">
            <label htmlFor="ch-url">URL</label>
            <input id="ch-url" className="input" type="url" value={form.url} onChange={set("url")}
              placeholder={editing ? `${channel.config.url} (leave empty to keep)` : "https://hooks.slack.com/services/…"} />
          </div>
        )}
        {form.type === "webhook" && (
          <div className="field">
            <label htmlFor="ch-secret">Signing secret (optional)</label>
            <input id="ch-secret" className="input" type="password" autoComplete="off" value={form.secret} onChange={set("secret")}
              placeholder={editing && channel.config.secret ? "(set; leave empty to keep)" : ""} />
          </div>
        )}
        <fieldset className="field">
          <legend>Send when</legend>
          <span className="auth-hint">Nothing ticked: every event.</span>
          {Object.entries(events).map(([name, label]) => (
            <label key={name} className="checkbox-inline">
              <input type="checkbox" checked={form.events.includes(name)} onChange={() => toggleEvent(name)} /> {label}
            </label>
          ))}
        </fieldset>
        <label className="checkbox-inline">
          <input type="checkbox" checked={form.only_problems} onChange={set("only_problems")} /> Only problems (warnings and errors)
        </label>
        <label className="checkbox-inline">
          <input type="checkbox" checked={form.enabled} onChange={set("enabled")} /> Enabled
        </label>
        <div className="btn-group">
          <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={busy || !form.name.trim()}>{busy ? "Saving…" : "Save"}</button>
        </div>
      </form>
    </Modal>
  );
}

export default function Notifications() {
  const { toast } = useStore();
  const confirm = useConfirm();
  const [data, setData] = useState(null);
  const [editing, setEditing] = useState(null); // null | "new" | channel

  const load = useCallback(async () => {
    try { setData((await api.getChannels()).data); }
    catch (err) { toast(err.message, "error"); setData({ channels: [], events: {} }); }
  }, [toast]);
  useEffect(() => { load(); }, [load]);

  const test = async (c) => {
    try {
      const res = await api.testChannel(c.id);
      toast(res.message, res.success ? "success" : "error");
    } catch (err) { toast(err.message, "error"); }
    load();
  };
  const remove = async (c) => {
    if (!(await confirm({ title: `Delete ${c.name}?`, message: "It stops receiving notifications.", confirmLabel: "Delete channel", danger: true }))) return;
    try { toast((await api.deleteChannel(c.id)).message, "success"); load(); }
    catch (err) { toast(err.message, "error"); }
  };

  const columns = [
    { key: "name", label: "Name", render: (c) => <strong>{c.name}</strong> },
    { key: "type", label: "Type", render: (c) => TYPES.find((t) => t.value === c.type)?.label },
    { key: "target", label: "Destination", render: (c) => (c.type === "email" ? c.config.to.join(", ") : c.config.url) },
    { key: "events", label: "Events", render: (c) => (c.events.length ? c.events.map((e) => EVENT_SHORT[e] || e).join(", ") : "All")
      + (c.only_problems ? " (problems only)" : "") },
    { key: "state", label: "Last delivery", render: (c) => (c.last_status
      ? (
        <>
          <Pill status={c.last_status === "ok" ? "success" : "error"} /> {new Date(c.last_sent_at).toLocaleString()}
          {c.last_error && <div className="cell-note">{c.last_error}</div>}
        </>
      )
      : <span className="muted">Nothing sent yet</span>) },
    { key: "enabled", label: "Enabled", render: (c) => (c.enabled ? "Yes" : "No") },
    { key: "actions", label: <span className="sr-only">Actions</span>, render: (c) => (
      <div className="btn-group">
        <button className="btn btn-sm btn-secondary" onClick={() => test(c)} aria-label={`Send a test message to ${c.name}`}>Test</button>
        <button className="btn btn-sm btn-secondary" onClick={() => setEditing(c)} aria-label={`Edit ${c.name}`}>Edit</button>
        <button className="btn btn-sm btn-danger" onClick={() => remove(c)} aria-label={`Delete ${c.name}`}>Delete</button>
      </div>
    ) },
  ];

  return (
    <>
      <PageHeader title="Notifications" subtitle="Where Habeny reports finished work and alerts">
        <button className="btn btn-primary" onClick={() => setEditing("new")}>New channel</button>
      </PageHeader>
      <div className="card">
        {data === null ? <Spinner /> : <DataTable columns={columns} rows={data.channels} emptyMsg="No channels yet. Add Slack, a webhook or email to hear about finished deployments and alerts." />}
      </div>
      {editing && data && (
        <ChannelModal channel={editing === "new" ? null : editing} events={data.events} emailAvailable={data.email_available}
          onClose={() => setEditing(null)} onSaved={load} />
      )}
    </>
  );
}
