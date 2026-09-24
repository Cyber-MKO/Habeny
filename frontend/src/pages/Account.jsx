import { useCallback, useEffect, useState } from "react";
import QRCode from "qrcode";
import { api } from "../api";
import { useAuth } from "../auth";
import { useStore } from "../store";
import { DataTable, Modal, PageHeader, Pill, Spinner } from "../components/UI";
import { useConfirm } from "../components/Confirm";
import { formatDateTime, t } from "../i18n";
import LanguagePicker from "../components/LanguagePicker";

const MIN_PASSWORD = 12; // server also rejects common passwords and ones containing the username

export const ROLES = [
  { value: "viewer", label: t("Viewer"), help: t("Read-only: dashboards, containers, reports") },
  { value: "operator", label: t("Operator"), help: t("Viewer + deploy, simulations, console, profiles") },
  { value: "admin", label: t("Admin"), help: t("Operator + manage users") },
];

const formatDate = (iso) => (iso ? formatDateTime(iso) : t("Never"));

function passwordProblem(password, confirm) {
  if (password.length < MIN_PASSWORD) return t("Password must be at least {n} characters.", { n: MIN_PASSWORD });
  if (password !== confirm) return t("Passwords don't match.");
  return null;
}

function ChangePassword() {
  const { user } = useAuth();
  const { toast } = useStore();
  const [form, setForm] = useState({ current: "", next: "", confirm: "" });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    const problem = passwordProblem(form.next, form.confirm);
    if (problem) return setError(problem);
    setError(null);
    setBusy(true);
    try {
      const res = await api.changeOwnPassword({ current_password: form.current, new_password: form.next });
      toast(res.message, "success");
      setForm({ current: "", next: "", confirm: "" });
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="card account-card" onSubmit={submit} noValidate>
      <div className="section-title">{t("Change password")}</div>
      <p className="account-help">{t("Changing your password signs you out on every other device.")}</p>
      {error && <div className="auth-error" role="alert">{error}</div>}
      {/* lets password managers associate the new password with this account */}
      <input type="text" name="username" autoComplete="username" value={user.username} readOnly hidden />
      <div className="field">
        <label htmlFor="pw-current">{t("Current password")}</label>
        <input id="pw-current" className="input" type="password" autoComplete="current-password" value={form.current} onChange={set("current")} />
      </div>
      <div className="field">
        <label htmlFor="pw-new">{t("New password")}</label>
        <input id="pw-new" className="input" type="password" autoComplete="new-password" value={form.next} onChange={set("next")} />
        <span className="auth-hint">{t("At least {n} characters.", { n: MIN_PASSWORD })}</span>
      </div>
      <div className="field">
        <label htmlFor="pw-confirm">{t("Confirm new password")}</label>
        <input id="pw-confirm" className="input" type="password" autoComplete="new-password" value={form.confirm} onChange={set("confirm")} />
      </div>
      <div>
        <button className="btn btn-primary" type="submit" disabled={busy || !form.current || !form.next}>
          {busy ? t("Saving…") : t("Change password")}
        </button>
      </div>
    </form>
  );
}

function RecoveryCodes({ codes, onDone }) {
  const { user } = useAuth();
  const text = codes.join("\n");
  const download = () => {
    const url = URL.createObjectURL(new Blob([`${t("Habeny recovery codes for {username}", { username: user.username })}\n\n${text}\n`], { type: "text/plain" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: `habeny-recovery-codes-${user.username}.txt` });
    a.click();
    URL.revokeObjectURL(url);
  };
  return (
    <>
      <div className="auth-notice">
        {t("Save these recovery codes somewhere safe. Each one signs you in once if you lose your phone. They won't be shown again.")}
      </div>
      <ul className="recovery-codes">{codes.map((c) => <li key={c}>{c}</li>)}</ul>
      <div className="btn-group">
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => navigator.clipboard?.writeText(text)}>{t("Copy")}</button>
        <button type="button" className="btn btn-secondary btn-sm" onClick={download}>{t("Download")}</button>
        <button type="button" className="btn btn-primary btn-sm" onClick={onDone}>{t("I've saved them")}</button>
      </div>
    </>
  );
}

function TwoFactor() {
  const { refresh } = useAuth();
  const { toast } = useStore();
  const [status, setStatus] = useState(null);
  // step: null | "password" (start setup) | "scan" | "codes" | "regenerate" | "disable"
  const [step, setStep] = useState(null);
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [enrolment, setEnrolment] = useState(null);
  const [codes, setCodes] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try { setStatus((await api.getMyTwoFactor()).data); }
    catch (err) { toast(err.message, "error"); }
  }, [toast]);
  useEffect(() => { load(); }, [load]);

  const go = (next) => { setStep(next); setPassword(""); setCode(""); setError(null); };
  const run = async (fn) => {
    setError(null);
    setBusy(true);
    try { await fn(); } catch (err) { setError(err.message); } finally { setBusy(false); }
  };

  const start = (e) => { e.preventDefault(); run(async () => {
    const { data } = await api.startTwoFactor({ current_password: password });
    const qr = await QRCode.toDataURL(data.otpauth_uri, { margin: 1, width: 200 });
    setEnrolment({ ...data, qr });
    go("scan");
  }); };
  const enable = (e) => { e.preventDefault(); run(async () => {
    const { data } = await api.enableTwoFactor({ code: code.trim() });
    setCodes(data.recovery_codes);
    setEnrolment(null);
    go("codes");
    load();
  }); };
  const regenerate = (e) => { e.preventDefault(); run(async () => {
    const { data } = await api.newRecoveryCodes({ current_password: password });
    setCodes(data.recovery_codes);
    go("codes");
    load();
  }); };
  const disable = (e) => { e.preventDefault(); run(async () => {
    const res = await api.disableTwoFactor({ current_password: password, code: code.trim() });
    toast(res.message, "success");
    go(null);
    load();
    refresh();
  }); };
  const finish = () => { setCodes(null); go(null); refresh(); };

  const passwordField = (
    <div className="field">
      <label htmlFor="tfa-password">{t("Current password")}</label>
      <input id="tfa-password" className="input" type="password" autoComplete="current-password" autoFocus
        value={password} onChange={(e) => setPassword(e.target.value)} />
    </div>
  );
  const codeField = (label) => (
    <div className="field">
      <label htmlFor="tfa-code">{label}</label>
      <input id="tfa-code" className="input auth-code-input" autoComplete="one-time-code" spellCheck={false}
        value={code} onChange={(e) => setCode(e.target.value)} />
    </div>
  );
  const cancel = <button type="button" className="btn btn-secondary" onClick={() => go(null)}>{t("Cancel")}</button>;

  let body;
  if (status === null) body = <Spinner />;
  else if (step === "codes") body = <RecoveryCodes codes={codes} onDone={finish} />;
  else if (step === "password" || step === "regenerate") body = (
    <form onSubmit={step === "password" ? start : regenerate} className="tfa-form" noValidate>
      {step === "regenerate" && <p className="account-help">{t("Your current recovery codes will stop working.")}</p>}
      {passwordField}
      <div className="btn-group">
        <button className="btn btn-primary" type="submit" disabled={busy || !password}>
          {step === "password" ? t("Continue") : t("Get new codes")}
        </button>
        {cancel}
      </div>
    </form>
  );
  else if (step === "scan") body = (
    <form onSubmit={enable} className="tfa-form" noValidate>
      <p className="account-help">
        {t("Scan this with an authenticator app (Google Authenticator, Microsoft Authenticator, 1Password, Authy…), then enter the 6-digit code it shows.")}
      </p>
      <div className="tfa-qr">
        <img src={enrolment.qr} alt={t("QR code for your authenticator app")} width="200" height="200" />
        <div className="account-help">
          {t("Can't scan? Enter this key:")} <code className="tfa-secret">{enrolment.secret.match(/.{1,4}/g).join(" ")}</code>
        </div>
      </div>
      {codeField(t("Code from the app"))}
      <div className="btn-group">
        <button className="btn btn-primary" type="submit" disabled={busy || !/^\d{6}$/.test(code.trim())}>{t("Turn on")}</button>
        {cancel}
      </div>
    </form>
  );
  else if (step === "disable") body = (
    <form onSubmit={disable} className="tfa-form" noValidate>
      {passwordField}
      {codeField(t("Authenticator or recovery code"))}
      <div className="btn-group">
        <button className="btn btn-danger" type="submit" disabled={busy || !password || code.trim().length < 6}>{t("Turn off")}</button>
        {cancel}
      </div>
    </form>
  );
  else if (status.enabled) body = (
    <>
      <p className="account-help">
        {t("On. Signing in needs a code from your authenticator app.")}{" "}
        {status.recovery_codes_left === 1 ? t("1 recovery code left.") : t("{n} recovery codes left.", { n: status.recovery_codes_left })}
      </p>
      <div className="btn-group">
        <button className="btn btn-secondary btn-sm" onClick={() => go("regenerate")}>{t("New recovery codes")}</button>
        <button className="btn btn-danger btn-sm" onClick={() => go("disable")}>{t("Turn off")}</button>
      </div>
    </>
  );
  else body = (
    <>
      <p className="account-help">
        {t("Off. Add a code from an authenticator app to your sign-in, so a stolen password isn't enough.")}
      </p>
      <div><button className="btn btn-primary btn-sm" onClick={() => go("password")}>{t("Turn on")}</button></div>
    </>
  );

  return (
    <div className="card account-card">
      <div className="account-users-head">
        <div className="section-title">{t("Two-factor authentication")}</div>
        {status && <span className={`tag ${status.enabled ? "tag-on" : ""}`}>{status.enabled ? t("on") : t("off")}</span>}
      </div>
      {error && <div className="auth-error" role="alert">{error}</div>}
      {body}
    </div>
  );
}

function describeAgent(ua) {
  if (!ua) return t("Unknown device");
  const browser = /Edg\//.test(ua) ? "Edge" : /Firefox\//.test(ua) ? "Firefox" : /Chrome\//.test(ua) ? "Chrome"
    : /Safari\//.test(ua) ? "Safari" : /curl|python|httpx/i.test(ua) ? t("API client") : t("Browser");
  const os = /Windows/.test(ua) ? "Windows" : /Mac OS X/.test(ua) ? "macOS" : /Android/.test(ua) ? "Android"
    : /iPhone|iPad/.test(ua) ? "iOS" : /Linux/.test(ua) ? "Linux" : "";
  return os ? t("{browser} on {os}", { browser, os }) : browser;
}

function Sessions() {
  const { toast } = useStore();
  const confirm = useConfirm();
  const [sessions, setSessions] = useState(null);
  const load = useCallback(async () => {
    try { setSessions((await api.getMySessions()).data.sessions); }
    catch (err) { toast(err.message, "error"); setSessions([]); }
  }, [toast]);
  useEffect(() => { load(); }, [load]);

  const end = async (s) => {
    try { toast((await api.endMySession(s.id)).message, "success"); load(); }
    catch (err) { toast(err.message, "error"); }
  };
  const endOthers = async () => {
    if (!(await confirm({ title: t("Sign out other sessions?"), message: t("Every other browser and device signed in to your account will be signed out."), confirmLabel: t("Sign out others") }))) return;
    try { toast((await api.endMyOtherSessions()).message, "success"); load(); }
    catch (err) { toast(err.message, "error"); }
  };

  const others = (sessions || []).filter((s) => !s.current).length;
  return (
    <div className="card account-card account-sessions">
      <div className="account-users-head">
        <div className="section-title">{t("Active sessions")}</div>
        <button className="btn btn-secondary btn-sm" onClick={endOthers} disabled={!others}>{t("Sign out all others")}</button>
      </div>
      <p className="account-help">{t("Browsers and devices signed in to your account.")}</p>
      {sessions === null ? <Spinner /> : (
        <ul className="session-list">
          {sessions.map((s) => (
            <li key={s.id} className="session-row">
              <div>
                <div className="session-device">
                  {describeAgent(s.user_agent)}{s.current && <span className="tag">{t("this browser")}</span>}
                </div>
                <div className="account-help">
                  {t("{ip} · active {active} · signed in {signedIn}", { ip: s.ip || t("unknown IP"), active: formatDate(s.last_seen_at), signedIn: formatDate(s.created_at) })}
                </div>
              </div>
              {!s.current && <button className="btn btn-sm btn-secondary" onClick={() => end(s)}>{t("Sign out")}</button>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const EXPIRY_CHOICES = [
  { value: "30", label: t("30 days") },
  { value: "90", label: t("90 days") },
  { value: "365", label: t("1 year") },
  { value: "never", label: t("Never") },
];

function NewTokenModal({ onClose, onCreated }) {
  const { user } = useAuth();
  const [form, setForm] = useState({ name: "", role: user.role, expires: "90" });
  const [created, setCreated] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const allowed = ROLES.slice(0, ROLES.findIndex((r) => r.value === user.role) + 1);

  const submit = async (e) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const res = await api.createMyToken({
        name: form.name.trim(), role: form.role,
        expires_in_days: form.expires === "never" ? null : Number(form.expires),
      });
      setCreated(res.data);
      onCreated();
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  };

  if (created) {
    const origin = window.location.origin;
    return (
      <Modal title={t("Token created")} onClose={onClose}>
        <div className="auth-notice">{t("Copy the token now. It isn't stored and won't be shown again.")}</div>
        <div className="token-box">
          <code aria-label={t("API token")}>{created.token}</code>
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => navigator.clipboard?.writeText(created.token)}>{t("Copy")}</button>
        </div>
        <p className="account-help">{t("Send it in the Authorization header, for example:")}</p>
        <pre className="code-sample">{`curl -H "Authorization: Bearer $HABENY_TOKEN" ${origin}/api/agents`}</pre>
        <div className="btn-group"><button type="button" className="btn btn-primary" onClick={onClose} data-autofocus="">{t("Done")}</button></div>
      </Modal>
    );
  }
  return (
    <Modal title={t("New API token")} onClose={onClose}>
      <form className="account-modal-form" onSubmit={submit} noValidate>
        <p className="account-help">
          {t("For scripts, CI pipelines, Prometheus and other Habeny consoles. A token acts as you, with at most your role.")}
        </p>
        {error && <div className="auth-error" role="alert">{error}</div>}
        <div className="field">
          <label htmlFor="token-name">{t("Name")}</label>
          <input id="token-name" className="input" value={form.name} onChange={set("name")} maxLength={64} placeholder={t("e.g. nightly-deploy")} />
          <span className="auth-hint">{t("What uses it, so you know what breaks if you revoke it.")}</span>
        </div>
        <div className="field">
          <label htmlFor="token-role">{t("Role")}</label>
          <select id="token-role" className="select" value={form.role} onChange={set("role")}>
            {allowed.map((r) => <option key={r.value} value={r.value}>{r.label}: {r.help}</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor="token-expiry">{t("Expires after")}</label>
          <select id="token-expiry" className="select" value={form.expires} onChange={set("expires")}>
            {EXPIRY_CHOICES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
          </select>
        </div>
        <div className="btn-group">
          <button type="button" className="btn btn-secondary" onClick={onClose}>{t("Cancel")}</button>
          <button type="submit" className="btn btn-primary" disabled={busy || !form.name.trim()}>{busy ? t("Creating…") : t("Create token")}</button>
        </div>
      </form>
    </Modal>
  );
}

function tokenState(tok) {
  if (tok.expires_at && new Date(tok.expires_at) < new Date()) return "expired";
  return tok.last_used_at ? "used" : "unused";
}

function ApiTokens() {
  const { user } = useAuth();
  const { toast } = useStore();
  const confirm = useConfirm();
  const [tokens, setTokens] = useState(null);
  const [everyone, setEveryone] = useState(false);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    try { setTokens((await (everyone ? api.getAllTokens() : api.getMyTokens())).data.tokens); }
    catch (err) { toast(err.message, "error"); setTokens([]); }
  }, [toast, everyone]);
  useEffect(() => { load(); }, [load]);

  const revoke = async (tok) => {
    const theirs = tok.user_id !== user.id;
    if (!(await confirm({
      title: t("Revoke {name}?", { name: tok.name }),
      message: theirs
        ? t("Anything using this token ({username}'s) stops working immediately.", { username: tok.username })
        : t("Anything using this token stops working immediately."),
      confirmLabel: t("Revoke token"), danger: true,
    }))) return;
    try { toast((await (theirs ? api.revokeToken(tok.id) : api.revokeMyToken(tok.id))).message, "success"); load(); }
    catch (err) { toast(err.message, "error"); }
  };

  const columns = [
    ...(everyone ? [{ key: "username", label: t("User") }] : []),
    { key: "name", label: t("Name"), render: (tok) => <><strong>{tok.name}</strong> <code className="muted">{tok.prefix}…</code></> },
    { key: "role", label: t("Role"), render: (tok) => <Pill status={tok.role} /> },
    { key: "expires_at", label: t("Expires"), render: (tok) => (tok.expires_at ? formatDate(tok.expires_at) : "Never") },
    { key: "last_used_at", label: t("Last used"), render: (tok) => (tok.last_used_at ? `${formatDate(tok.last_used_at)}${tok.last_used_ip ? ` from ${tok.last_used_ip}` : ""}` : "Never") },
    { key: "state", label: t("State"), render: (tok) => <Pill status={tokenState(tok)} /> },
    { key: "actions", label: <span className="sr-only">{t("Actions")}</span>, render: (tok) => (
      <button className="btn btn-sm btn-danger" onClick={() => revoke(tok)} aria-label={t("Revoke {name}", { name: tok.name })}>{t("Revoke")}</button>
    ) },
  ];

  return (
    <div className="card account-card account-wide">
      <div className="account-users-head">
        <div className="section-title">{t("API tokens")}</div>
        <div className="btn-group">
          {user.is_admin && (
            <label className="checkbox-inline">
              <input type="checkbox" checked={everyone} onChange={(e) => setEveryone(e.target.checked)} /> {t("Everyone's tokens")}
            </label>
          )}
          <button className="btn btn-primary btn-sm" onClick={() => setCreating(true)}>{t("New token")}</button>
        </div>
      </div>
      <p className="account-help">
        {t("Let scripts and CI use the API with this header:")} <code>Authorization: Bearer &lt;token&gt;</code>.{" "}
        {t("Tokens can't change account settings (password, two-factor, tokens). Create one per use, so you can revoke it on its own.")}
      </p>
      {tokens === null ? <Spinner /> : <DataTable columns={columns} rows={tokens} emptyMsg={t("No API tokens yet")} label={t("API tokens")} />}
      {creating && <NewTokenModal onClose={() => setCreating(false)} onCreated={load} />}
    </div>
  );
}

function AddUserModal({ onClose, onCreated }) {
  const { toast } = useStore();
  const [form, setForm] = useState({ username: "", password: "", confirm: "", role: "viewer" });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    const problem = passwordProblem(form.password, form.confirm);
    if (problem) return setError(problem);
    setBusy(true);
    try {
      const res = await api.createUser({ username: form.username.trim(), password: form.password, role: form.role });
      toast(res.message, "success");
      onCreated();
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };

  return (
    <Modal title={t("Add user")} onClose={onClose}>
      <form className="account-modal-form" onSubmit={submit} noValidate>
        {error && <div className="auth-error" role="alert">{error}</div>}
        <div className="field">
          <label htmlFor="nu-username">{t("Username")}</label>
          <input id="nu-username" className="input" autoComplete="off" autoFocus value={form.username}
            onChange={(e) => setForm({ ...form, username: e.target.value })} />
          <span className="auth-hint">{t("3–32 characters: letters, numbers, dot, dash, underscore.")}</span>
        </div>
        <div className="field">
          <label htmlFor="nu-password">{t("Password")}</label>
          <input id="nu-password" className="input" type="password" autoComplete="new-password" value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="nu-confirm">{t("Confirm password")}</label>
          <input id="nu-confirm" className="input" type="password" autoComplete="new-password" value={form.confirm}
            onChange={(e) => setForm({ ...form, confirm: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="nu-role">{t("Role")}</label>
          <select id="nu-role" className="select" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
            {ROLES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
          </select>
          <span className="auth-hint">{ROLES.find((r) => r.value === form.role)?.help}</span>
        </div>
        <div className="btn-group">
          <button className="btn btn-primary" type="submit" disabled={busy || !form.username.trim() || !form.password}>
            {busy ? t("Creating…") : t("Create user")}
          </button>
          <button className="btn btn-secondary" type="button" onClick={onClose}>{t("Cancel")}</button>
        </div>
      </form>
    </Modal>
  );
}

function ResetPasswordModal({ user, onClose }) {
  const { toast } = useStore();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    const problem = passwordProblem(password, confirm);
    if (problem) return setError(problem);
    setBusy(true);
    try {
      const res = await api.resetUserPassword(user.id, { new_password: password });
      toast(res.message, "success");
      onClose();
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };

  return (
    <Modal title={t("Reset password for {username}", { username: user.username })} onClose={onClose}>
      <form className="account-modal-form" onSubmit={submit} noValidate>
        <p className="account-help">{t("They'll be signed out everywhere and need the new password to sign in.")}</p>
        {error && <div className="auth-error" role="alert">{error}</div>}
        <div className="field">
          <label htmlFor="rp-password">{t("New password")}</label>
          <input id="rp-password" className="input" type="password" autoComplete="new-password" autoFocus value={password}
            onChange={(e) => setPassword(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="rp-confirm">{t("Confirm new password")}</label>
          <input id="rp-confirm" className="input" type="password" autoComplete="new-password" value={confirm}
            onChange={(e) => setConfirm(e.target.value)} />
        </div>
        <div className="btn-group">
          <button className="btn btn-primary" type="submit" disabled={busy || !password}>
            {busy ? t("Saving…") : t("Reset password")}
          </button>
          <button className="btn btn-secondary" type="button" onClick={onClose}>{t("Cancel")}</button>
        </div>
      </form>
    </Modal>
  );
}

function Users() {
  const { user: me } = useAuth();
  const { toast } = useStore();
  const confirm = useConfirm();
  const [users, setUsers] = useState(null);
  const [adding, setAdding] = useState(false);
  const [resetting, setResetting] = useState(null);

  const load = useCallback(async () => {
    try { setUsers((await api.getUsers()).data.users); }
    catch (err) { toast(err.message, "error"); setUsers([]); }
  }, [toast]);

  useEffect(() => { load(); }, [load]);

  const changeRole = async (u, role) => {
    if (role === u.role) return;
    try {
      const res = await api.updateUser(u.id, { role });
      toast(res.message, "success");
      load();
    } catch (err) { toast(err.message, "error"); }
  };

  const signOutEverywhere = async (u) => {
    if (!(await confirm({ title: t("Sign {username} out everywhere?", { username: u.username }), message: t("They'll be signed out of every browser and device. Their API tokens keep working."), confirmLabel: t("Sign out") }))) return;
    try { toast((await api.endUserSessions(u.id)).message, "success"); }
    catch (err) { toast(err.message, "error"); }
  };

  const resetTwoFactor = async (u) => {
    if (!(await confirm({ title: t("Reset two-factor for {username}?", { username: u.username }), message: t("Use this when they've lost their authenticator and recovery codes. They'll be signed out and can set it up again."), confirmLabel: t("Reset two-factor"), danger: true }))) return;
    try { toast((await api.resetUserTwoFactor(u.id)).message, "success"); load(); }
    catch (err) { toast(err.message, "error"); }
  };

  const remove = async (u) => {
    if (!(await confirm({ title: t("Delete {username}?", { username: u.username }), message: t("They'll be signed out immediately and their API tokens stop working."), confirmLabel: t("Delete user"), danger: true }))) return;
    try {
      const res = await api.deleteUser(u.id);
      toast(res.message, "success");
      load();
    } catch (err) { toast(err.message, "error"); }
  };

  const columns = [
    { key: "username", label: t("Username"), render: (u) => (
      <span className="account-username">
        {u.username}{u.id === me.id && <span className="tag">{t("you")}</span>}{u.sso && <span className="tag">SSO</span>}
      </span>
    )},
    { key: "role", label: t("Role"), render: (u) => u.id === me.id ? <Pill status={u.role} /> : (
      <select className="select account-role-select" value={u.role} aria-label={t("Role of {username}", { username: u.username })}
        onChange={(e) => changeRole(u, e.target.value)}>
        {ROLES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
      </select>
    )},
    { key: "totp_enabled", label: "2FA", render: (u) => u.sso ? <span className="account-help">{t("via SSO")}</span> : (
      <span className={`tag ${u.totp_enabled ? "tag-on" : ""}`}>{u.totp_enabled ? t("on") : t("off")}</span>
    )},
    { key: "last_login_at", label: t("Last sign-in"), render: (u) => formatDate(u.last_login_at) },
    { key: "created_at", label: t("Created"), render: (u) => new Date(u.created_at).toLocaleDateString() },
    { key: "actions", label: "", render: (u) => u.id === me.id ? (
      <span className="account-help">{me.sso ? "" : t("Use “Change password” above")}</span>
    ) : (
      <div className="btn-group">
        {!u.sso && <button className="btn btn-sm btn-secondary" onClick={() => setResetting(u)}>{t("Reset password")}</button>}
        <button className="btn btn-sm btn-secondary" onClick={() => signOutEverywhere(u)}>{t("Sign out everywhere")}</button>
        {u.totp_enabled && <button className="btn btn-sm btn-secondary" onClick={() => resetTwoFactor(u)}>{t("Reset 2FA")}</button>}
        <button className="btn btn-sm btn-danger" onClick={() => remove(u)}>{t("Delete")}</button>
      </div>
    )},
  ];

  return (
    <div className="section">
      <div className="account-users-head">
        <div className="section-title">{t("Users")}</div>
        <button className="btn btn-primary btn-sm" onClick={() => setAdding(true)}>{t("Add user")}</button>
      </div>
      {users === null ? <Spinner /> : <DataTable columns={columns} rows={users} emptyMsg={t("No users")} label={t("Users")} />}
      {adding && <AddUserModal onClose={() => setAdding(false)} onCreated={() => { setAdding(false); load(); }} />}
      {resetting && <ResetPasswordModal user={resetting} onClose={() => setResetting(null)} />}
    </div>
  );
}

const formatSize = (bytes) => (bytes >= 1e6 ? `${(bytes / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1e3))} kB`);

function Backups() {
  const { toast } = useStore();
  const [info, setInfo] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try { setInfo((await api.getBackups()).data); }
    catch (err) { toast(err.message, "error"); setInfo({ backups: [], schedule: null }); }
  }, [toast]);
  useEffect(() => { load(); }, [load]);

  const backUpNow = async () => {
    setBusy(true);
    try { toast((await api.createBackup()).message, "success"); load(); }
    catch (err) { toast(err.message, "error"); }
    finally { setBusy(false); }
  };

  const schedule = info?.schedule;
  const columns = [
    { key: "created_at", label: t("Taken"), render: (b) => formatDate(b.created_at) },
    { key: "label", label: t("Type"), render: (b) => <span className="tag">{b.label}</span> },
    { key: "size_bytes", label: t("Size"), render: (b) => formatSize(b.size_bytes) },
    { key: "download", label: "", render: (b) => (
      <a className="btn btn-sm btn-secondary" href={api.backupDownloadUrl(b.name)} download>{t("Download")}</a>
    )},
  ];
  return (
    <div className="section">
      <div className="account-users-head">
        <div className="section-title">{t("Backups")}</div>
        <button className="btn btn-primary btn-sm" onClick={backUpNow} disabled={busy}>
          {busy ? t("Backing up…") : t("Back up now")}
        </button>
      </div>
      <p className="account-help">
        {schedule && (schedule.interval_hours > 0
          ? t("A full backup is taken every {interval_hours} h; the newest {keep} are kept in {directory}. ", { interval_hours: schedule.interval_hours, keep: schedule.keep, directory: schedule.directory })
          : t("Scheduled backups are off (HABENY_BACKUP_INTERVAL_HOURS=0). "))}
        {t("Each contains the database, the key that decrypts stored secrets, reports and settings: keep downloaded copies somewhere only admins can read. Restore with")} <code>sudo habeny backup restore FILE</code>.
      </p>
      {schedule?.last_scheduled_error && (
        <div className="auth-error" role="alert">{t("The last scheduled backup failed:")} {schedule.last_scheduled_error}</div>
      )}
      {info === null ? <Spinner /> : <DataTable columns={columns} rows={info.backups} emptyMsg={t("No backups yet")} label={t("Backups")} />}
    </div>
  );
}

export default function Account() {
  const { user } = useAuth();
  return (
    <>
      <PageHeader
        title={t("Account")}
        subtitle={user.is_admin ? t("Your sign-in security and who can sign in") : t("Your sign-in security")}
      />
      <div className="section">
        <div className="account-me">
          {t("Signed in as")} <strong>{user.username}</strong>
          <Pill status={user.role} />
          {user.team && <span className="tag">{t("team {name}", { name: user.team.name })}</span>}
        </div>
        <div className="account-grid">
          {user.sso ? (
            <div className="card account-card">
              <div className="section-title">{t("Single sign-on")}</div>
              <p className="account-help">
                {t("You sign in through your organization's identity provider. Change your password and two-factor settings there.")}
              </p>
            </div>
          ) : (
            <>
              <ChangePassword />
              <TwoFactor />
            </>
          )}
          <Sessions />
          <div className="card account-card">
            <div className="section-title">{t("Language")}</div>
            <p className="account-help">{t("The language of this interface in this browser. Messages from the server stay in English.")}</p>
            <LanguagePicker />
          </div>
        </div>
      </div>
      <div className="section"><ApiTokens /></div>
      {user.is_admin && <Users />}
      {user.is_admin && <Backups />}
    </>
  );
}
