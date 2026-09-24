import { useCallback, useEffect, useState } from "react";
import { NavLink } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { useStore } from "../store";
import { PageHeader, Spinner } from "../components/UI";
import { t } from "../i18n";

const STATE_LABELS = {
  off: () => t("Not required"),
  active: () => t("Active"),
  expiring: () => t("Expiring soon"),
  grace: () => t("Expired (grace period)"),
  expired: () => t("Expired"),
  trial: () => t("Trial"),
  trial_ended: () => t("Trial ended"),
  invalid: () => t("Invalid license"),
};

const STATE_PILL = { active: "pill-active", off: "pill-unknown", trial: "pill-pending", expiring: "pill-partial", grace: "pill-partial" };

function InstallForm({ onInstalled }) {
  const { toast } = useStore();
  const [text, setText] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const readFile = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    file.text().then(setText).catch(() => setError(t("Can't read that file")));
  };
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await api.installLicense({ license: text.trim() });
      toast(res.message, "success");
      setText("");
      onInstalled();
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  };
  return (
    <form className="license-form" onSubmit={submit} noValidate>
      <div className="section-title">{t("Install a license")}</div>
      {error && <div className="auth-error" role="alert">{error}</div>}
      <div className="field">
        <label htmlFor="license-file">{t("License file")}</label>
        <input id="license-file" className="input" type="file" accept=".license,.key,.txt,text/plain" onChange={readFile} />
      </div>
      <div className="field">
        <label htmlFor="license-text">{t("Or paste the license")}</label>
        <textarea id="license-text" className="input textarea" rows={4} value={text} onChange={(e) => setText(e.target.value)}
          placeholder="HBYL1.…" spellCheck={false} />
      </div>
      <button type="submit" className="btn btn-primary" disabled={busy || !text.trim()}>{t("Install license")}</button>
    </form>
  );
}

export default function License() {
  const { user } = useAuth();
  const [info, setInfo] = useState(null);
  const [error, setError] = useState(null);
  const load = useCallback(() => {
    api.getLicense().then((res) => { setInfo(res.data); setError(null); }).catch((err) => setError(err.message));
  }, []);
  useEffect(() => { load(); }, [load]);

  const lic = info?.license;
  return (
    <>
      <PageHeader title={t("License")} subtitle={t("This server's Habeny license")} />
      <div className="page-stack">
        <div className="card">
          {error && <div className="auth-error" role="alert">{error}</div>}
          {!info && !error && <Spinner />}
          {info && (
            <>
              <p>
                <span className={`pill ${STATE_PILL[info.state] || "pill-failed"}`}>{(STATE_LABELS[info.state] || (() => info.state))()}</span>{" "}
                {info.message}
              </p>
              <table className="kv-table">
                <tbody>
                  <tr><th scope="row">{t("Server ID")}</th><td><code>{info.server_id}</code></td></tr>
                  {lic && <tr><th scope="row">{t("License number")}</th><td>{lic.id}</td></tr>}
                  {lic && <tr><th scope="row">{t("Licensed to")}</th><td>{lic.customer}</td></tr>}
                  {lic && <tr><th scope="row">{t("Issued")}</th><td>{lic.issued}</td></tr>}
                  {lic && <tr><th scope="row">{t("Expires")}</th><td>{lic.expires || t("Never")}</td></tr>}
                  {lic && <tr><th scope="row">{t("Container limit")}</th><td>{lic.max_containers ?? t("No limit")}</td></tr>}
                  {!lic && info.trial_ends && <tr><th scope="row">{t("Trial ends")}</th><td>{info.trial_ends}</td></tr>}
                </tbody>
              </table>
              {info.state !== "off" && (
                <p className="account-help">
                  {t("To get a license, send the server ID above to your Habeny vendor (or run habeny license request on the server). A license works on this server only. Without a valid license, new deployments, simulations, benchmarks and log uploads are refused; viewing and managing existing containers always work.")}
                </p>
              )}
            </>
          )}
        </div>
        {info && info.state !== "off" && user.is_admin && (
          <div className="card"><InstallForm onInstalled={load} /></div>
        )}
        <div className="card">
          <div className="section-title">{t("Open-source licenses")}</div>
          <p className="account-help">
            {t("Habeny includes open-source software. Its licenses and notices are listed in")}{" "}
            <a href="/THIRD_PARTY_NOTICES.txt" target="_blank" rel="noreferrer">THIRD_PARTY_NOTICES.txt</a>.
          </p>
        </div>
      </div>
    </>
  );
}

// Shown in the header when the license needs attention
export function LicenseBanner() {
  const [info, setInfo] = useState(null);
  useEffect(() => {
    let stopped = false;
    const load = () => api.getLicense().then((res) => { if (!stopped) setInfo(res.data); }).catch(() => {});
    load();
    const timer = setInterval(load, 3600000);
    return () => { stopped = true; clearInterval(timer); };
  }, []);
  if (!info || ["off", "active"].includes(info.state)) return null;
  if (info.state === "trial" && info.days_left > 7) return null;
  const blocked = !info.allows_new_work;
  return (
    <NavLink to="/license" className={`header-alerts${blocked ? "" : " warning"}`} title={info.message}>
      {t("License")}: {(STATE_LABELS[info.state] || (() => info.state))()}
    </NavLink>
  );
}
