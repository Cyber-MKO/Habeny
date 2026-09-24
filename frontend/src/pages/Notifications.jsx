import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { useStore } from "../store";
import { useConfirm } from "../components/Confirm";
import { DataTable, Modal, PageHeader, Pill, Spinner } from "../components/UI";
import { formatDateTime, t } from "../i18n";

const TYPES = [
  { value: "slack", label: "Slack", help: t("An incoming-webhook URL from Slack (or a Slack-compatible chat such as Mattermost).") },
  { value: "webhook", label: t("Webhook"), help: t("Habeny POSTs JSON to your URL. With a secret, each request is signed (X-Habeny-Signature).") },
  { value: "email", label: t("Email"), help: t("Sent through the mail server set in the configuration (HABENY_SMTP_*).") },
];

const EVENT_SHORT = {
  "deployment.finished": t("Deployments"), "simulation.finished": t("Simulations"), "benchmark.finished": t("Benchmarks"),
  "alert.firing": t("Alerts"), "alert.resolved": t("Alerts cleared"),
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
    <Modal title={editing ? t("Edit {name}", { name: channel.name }) : t("New notification channel")} onClose={onClose}>
      <form className="account-modal-form" onSubmit={submit} noValidate>
        {error && <div className="auth-error" role="alert">{error}</div>}
        <div className="field">
          <label htmlFor="ch-name">{t("Name")}</label>
          <input id="ch-name" className="input" value={form.name} onChange={set("name")} maxLength={64} placeholder={t("e.g. #soc-alerts")} />
        </div>
        <fieldset className="field" disabled={editing}>
          <legend>{t("Type")}</legend>
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
            {form.type === "email" && !emailAvailable && t(" Email is off until HABENY_SMTP_HOST is set.")}
          </span>
        </fieldset>
        {form.type === "email" ? (
          <div className="field">
            <label htmlFor="ch-to">{t("Send to")}</label>
            <input id="ch-to" className="input" value={form.to} onChange={set("to")} placeholder={t("soc@example.com, oncall@example.com")} />
          </div>
        ) : (
          <div className="field">
            <label htmlFor="ch-url">URL</label>
            <input id="ch-url" className="input" type="url" value={form.url} onChange={set("url")}
              placeholder={editing ? t("{url} (leave empty to keep)", { url: channel.config.url }) : "https://hooks.slack.com/services/…"} />
          </div>
        )}
        {form.type === "webhook" && (
          <div className="field">
            <label htmlFor="ch-secret">{t("Signing secret (optional)")}</label>
            <input id="ch-secret" className="input" type="password" autoComplete="off" value={form.secret} onChange={set("secret")}
              placeholder={editing && channel.config.secret ? t("(set; leave empty to keep)") : ""} />
          </div>
        )}
        <fieldset className="field">
          <legend>{t("Send when")}</legend>
          <span className="auth-hint">{t("Nothing ticked: every event.")}</span>
          {Object.entries(events).map(([name, label]) => (
            <label key={name} className="checkbox-inline">
              <input type="checkbox" checked={form.events.includes(name)} onChange={() => toggleEvent(name)} /> {label}
            </label>
          ))}
        </fieldset>
        <label className="checkbox-inline">
          <input type="checkbox" checked={form.only_problems} onChange={set("only_problems")} /> {t("Only problems (warnings and errors)")}
        </label>
        <label className="checkbox-inline">
          <input type="checkbox" checked={form.enabled} onChange={set("enabled")} /> {t("Enabled")}
        </label>
        <div className="btn-group">
          <button type="button" className="btn btn-secondary" onClick={onClose}>{t("Cancel")}</button>
          <button type="submit" className="btn btn-primary" disabled={busy || !form.name.trim()}>{busy ? t("Saving…") : t("Save")}</button>
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
    if (!(await confirm({ title: t("Delete {name}?", { name: c.name }), message: t("It stops receiving notifications."), confirmLabel: t("Delete channel"), danger: true }))) return;
    try { toast((await api.deleteChannel(c.id)).message, "success"); load(); }
    catch (err) { toast(err.message, "error"); }
  };

  const columns = [
    { key: "name", label: t("Name"), render: (c) => <strong>{c.name}</strong> },
    { key: "type", label: t("Type"), render: (c) => TYPES.find((t) => t.value === c.type)?.label },
    { key: "target", label: t("Destination"), render: (c) => (c.type === "email" ? c.config.to.join(", ") : c.config.url) },
    { key: "events", label: t("Events"), render: (c) => (c.events.length ? c.events.map((e) => EVENT_SHORT[e] || e).join(", ") : "All")
      + (c.only_problems ? " (problems only)" : "") },
    { key: "state", label: t("Last delivery"), render: (c) => (c.last_status
      ? (
        <>
          <Pill status={c.last_status === "ok" ? "success" : "error"} /> {formatDateTime(c.last_sent_at)}
          {c.last_error && <div className="cell-note">{c.last_error}</div>}
        </>
      )
      : <span className="muted">{t("Nothing sent yet")}</span>) },
    { key: "enabled", label: t("Enabled"), render: (c) => (c.enabled ? "Yes" : "No") },
    { key: "actions", label: <span className="sr-only">{t("Actions")}</span>, render: (c) => (
      <div className="btn-group">
        <button className="btn btn-sm btn-secondary" onClick={() => test(c)} aria-label={t("Send a test message to {name}", { name: c.name })}>{t("Test")}</button>
        <button className="btn btn-sm btn-secondary" onClick={() => setEditing(c)} aria-label={t("Edit {name}", { name: c.name })}>{t("Edit")}</button>
        <button className="btn btn-sm btn-danger" onClick={() => remove(c)} aria-label={t("Delete {name}", { name: c.name })}>{t("Delete")}</button>
      </div>
    ) },
  ];

  return (
    <>
      <PageHeader title={t("Notifications")} subtitle={t("Where Habeny reports finished work and alerts")}>
        <button className="btn btn-primary" onClick={() => setEditing("new")}>{t("New channel")}</button>
      </PageHeader>
      <div className="card">
        {data === null ? <Spinner /> : <DataTable columns={columns} rows={data.channels} emptyMsg={t("No channels yet. Add Slack, a webhook or email to hear about finished deployments and alerts.")} />}
      </div>
      {editing && data && (
        <ChannelModal channel={editing === "new" ? null : editing} events={data.events} emailAvailable={data.email_available}
          onClose={() => setEditing(null)} onSaved={load} />
      )}
    </>
  );
}
