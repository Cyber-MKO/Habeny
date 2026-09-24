import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { useStore } from "../store";
import { useHosts } from "../hosts";
import { useConfirm } from "../components/Confirm";
import { DataTable, Modal, PageHeader, Pill, Spinner } from "../components/UI";
import { t } from "../i18n";

function HostModal({ host, teams, onClose, onSaved }) {
  const { toast } = useStore();
  const [form, setForm] = useState({ name: host?.name || "", url: host?.url || "", token: "", team_id: host?.team_id ?? "" });
  const [fingerprint, setFingerprint] = useState(null); // shown for the admin to confirm
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async (e) => {
    e?.preventDefault();
    setError(null);
    setBusy(true);
    const body = { name: form.name.trim(), url: form.url.trim(), token: form.token.trim(),
      team_id: form.team_id === "" ? null : Number(form.team_id), fingerprint };
    try {
      const res = host ? await api.updateHost(host.id, body) : await api.addHost(body);
      if (res.error === "fingerprint_needed") {
        setFingerprint(res.data.fingerprint);
        return;
      }
      toast(res.message, "success");
      onSaved();
      onClose();
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  };

  return (
    <Modal title={host ? t("Edit {name}", { name: host.name }) : t("Add a host")} onClose={onClose}>
      <form className="account-modal-form" onSubmit={submit} noValidate>
        {!host && (
          <ol className="steps">
            <li>{t("On the other server, sign in and create an API token (Account → API tokens), operator role for full control.")}</li>
            <li>{t("Enter its address and the token here.")}</li>
          </ol>
        )}
        {error && <div className="auth-error" role="alert">{error}</div>}
        <div className="field">
          <label htmlFor="host-name">{t("Name")}</label>
          <input id="host-name" className="input" value={form.name} onChange={set("name")} maxLength={64} placeholder={t("e.g. lab-2")} />
        </div>
        {!host && (
          <div className="field">
            <label htmlFor="host-url">{t("Address")}</label>
            <input id="host-url" className="input" type="url" value={form.url} onChange={set("url")} placeholder="https://10.0.0.12:9000" />
          </div>
        )}
        <div className="field">
          <label htmlFor="host-token">{t("API token")}{host ? t(" (leave empty to keep)") : ""}</label>
          <input id="host-token" className="input" type="password" autoComplete="off" value={form.token} onChange={set("token")} placeholder="hby_…" />
        </div>
        <div className="field">
          <label htmlFor="host-team">{t("Available to")}</label>
          <select id="host-team" className="select" value={form.team_id} onChange={set("team_id")}>
            <option value="">{t("Everyone")}</option>
            {teams.map((team) => <option key={team.id} value={team.id}>{t("Team {name} (and admins)", { name: team.name })}</option>)}
          </select>
        </div>
        {fingerprint && (
          <div className="auth-notice" role="alert">
            <p>
              {t("This host uses a certificate that isn't from a trusted authority (Habeny's self-signed one). Before trusting it, check that the host shows the same fingerprint when you run this command on it:")}{" "}
              <code>sudo habeny tls fingerprint</code>
            </p>
            <code className="fingerprint">{fingerprint}</code>
          </div>
        )}
        <div className="btn-group">
          <button type="button" className="btn btn-secondary" onClick={onClose}>{t("Cancel")}</button>
          <button type="submit" className="btn btn-primary" disabled={busy || !form.name.trim() || (!host && (!form.url.trim() || !form.token.trim()))}>
            {busy ? t("Checking…") : fingerprint ? t("It matches: trust and add") : host ? t("Save") : t("Add host")}
          </button>
        </div>
      </form>
    </Modal>
  );
}

export default function Hosts() {
  const { user } = useAuth();
  const { toast } = useStore();
  const confirm = useConfirm();
  const { hostId, selectHost, refreshHosts } = useHosts();
  const [hosts, setHosts] = useState(null);
  const [teams, setTeams] = useState([]);
  const [editing, setEditing] = useState(null);

  const load = useCallback(async () => {
    try { setHosts((await api.getHostsOverview()).data.hosts); }
    catch (err) { toast(err.message, "error"); setHosts([]); }
    refreshHosts();
  }, [toast, refreshHosts]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (user.is_admin) api.getTeams().then((res) => setTeams(res.data.teams)).catch(() => {});
  }, [user.is_admin]);

  const remove = async (h) => {
    if (!(await confirm({ title: t("Remove {name}?", { name: h.name }), message: t("This console stops managing it. The server and its containers aren't touched; revoke the token there too."), confirmLabel: t("Remove host"), danger: true }))) return;
    try {
      toast((await api.removeHost(h.id)).message, "success");
      if (hostId === h.id) selectHost(null);
      load();
    } catch (err) { toast(err.message, "error"); }
  };

  const columns = [
    { key: "name", label: t("Host"), render: (h) => <><strong>{h.name}</strong><div className="muted">{h.url}</div></> },
    { key: "status", label: t("Status"), render: (h) => (
      <>
        <Pill status={h.status === "ok" ? "online" : "offline"} />
        {h.error && <div className="cell-note">{h.error}</div>}
      </>
    ) },
    { key: "version", label: t("Version"), render: (h) => (h.version ? `Habeny ${h.version}` : "—") },
    { key: "containers", label: t("Containers"), render: (h) => (h.containers ?? "—") + (h.running != null ? ` (${h.running} running)` : "") },
    { key: "alerts", label: t("Alerts"), render: (h) => (h.alerts?.length ? <span className="cell-note">{h.alerts.map((a) => a.label).join(", ")}</span> : h.status === "ok" ? "None" : "—") },
    { key: "actions", label: <span className="sr-only">{t("Actions")}</span>, render: (h) => (
      <div className="btn-group">
        <button className="btn btn-sm btn-primary" onClick={() => selectHost(h.id)} disabled={hostId === h.id || h.status !== "ok"}>
          {hostId === h.id ? t("Working on it") : t("Work on this host")}
        </button>
        {user.is_admin && <button className="btn btn-sm btn-secondary" onClick={() => setEditing(h)} aria-label={t("Edit {name}", { name: h.name })}>{t("Edit")}</button>}
        {user.is_admin && <button className="btn btn-sm btn-danger" onClick={() => remove(h)} aria-label={t("Remove {name}", { name: h.name })}>{t("Remove")}</button>}
      </div>
    ) },
  ];

  return (
    <>
      <PageHeader title={t("Hosts")} subtitle={t("Other Habeny servers (LXC hosts) you can manage from this console")}>
        <button className="btn btn-secondary" onClick={load}>{t("Refresh")}</button>
        {user.is_admin && <button className="btn btn-primary" onClick={() => setEditing("new")}>{t("Add host")}</button>}
      </PageHeader>
      <p className="account-help">
        {t("Each LXC host runs its own Habeny. Pick one here, or in the")} <strong>{t("Server")}</strong> {t("menu at the top of the sidebar, and every page works on that host: containers, deployments, simulations, metrics and the console. What you can do there is limited by the host's API token and by your own role here.")}
      </p>
      <div className="card">
        {hosts === null ? <Spinner /> : <DataTable columns={columns} rows={hosts} emptyMsg={user.is_admin ? t("No other hosts yet. Add one to manage several LXC hosts from here.") : t("No other hosts have been added.")} />}
      </div>
      {editing && <HostModal host={editing === "new" ? null : editing} teams={teams} onClose={() => setEditing(null)} onSaved={load} />}
    </>
  );
}
