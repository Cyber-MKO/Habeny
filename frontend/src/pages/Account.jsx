import { useCallback, useEffect, useState } from "react";
import QRCode from "qrcode";
import { api } from "../api";
import { useAuth } from "../auth";
import { useStore } from "../store";
import { DataTable, Modal, PageHeader, Pill, Spinner } from "../components/UI";

const MIN_PASSWORD = 12; // server also rejects common passwords and ones containing the username

export const ROLES = [
  { value: "viewer", label: "Viewer", help: "Read-only: dashboards, containers, reports" },
  { value: "operator", label: "Operator", help: "Viewer + deploy, simulations, console, profiles" },
  { value: "admin", label: "Admin", help: "Operator + manage users" },
];

const formatDate = (iso) => (iso ? new Date(iso).toLocaleString() : "Never");

function passwordProblem(password, confirm) {
  if (password.length < MIN_PASSWORD) return `Password must be at least ${MIN_PASSWORD} characters.`;
  if (password !== confirm) return "Passwords don't match.";
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
      <div className="section-title">Change password</div>
      <p className="account-help">Changing your password signs you out on every other device.</p>
      {error && <div className="auth-error" role="alert">{error}</div>}
      {/* lets password managers associate the new password with this account */}
      <input type="text" name="username" autoComplete="username" value={user.username} readOnly hidden />
      <div className="field">
        <label htmlFor="pw-current">Current password</label>
        <input id="pw-current" className="input" type="password" autoComplete="current-password" value={form.current} onChange={set("current")} />
      </div>
      <div className="field">
        <label htmlFor="pw-new">New password</label>
        <input id="pw-new" className="input" type="password" autoComplete="new-password" value={form.next} onChange={set("next")} />
        <span className="auth-hint">At least {MIN_PASSWORD} characters.</span>
      </div>
      <div className="field">
        <label htmlFor="pw-confirm">Confirm new password</label>
        <input id="pw-confirm" className="input" type="password" autoComplete="new-password" value={form.confirm} onChange={set("confirm")} />
      </div>
      <div>
        <button className="btn btn-primary" type="submit" disabled={busy || !form.current || !form.next}>
          {busy ? "Saving…" : "Change password"}
        </button>
      </div>
    </form>
  );
}

function RecoveryCodes({ codes, onDone }) {
  const { user } = useAuth();
  const text = codes.join("\n");
  const download = () => {
    const url = URL.createObjectURL(new Blob([`Habeny recovery codes for ${user.username}\n\n${text}\n`], { type: "text/plain" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: `habeny-recovery-codes-${user.username}.txt` });
    a.click();
    URL.revokeObjectURL(url);
  };
  return (
    <>
      <div className="auth-notice">
        Save these recovery codes somewhere safe. Each one signs you in once if you lose your phone.
        They won't be shown again.
      </div>
      <ul className="recovery-codes">{codes.map((c) => <li key={c}>{c}</li>)}</ul>
      <div className="btn-group">
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => navigator.clipboard?.writeText(text)}>Copy</button>
        <button type="button" className="btn btn-secondary btn-sm" onClick={download}>Download</button>
        <button type="button" className="btn btn-primary btn-sm" onClick={onDone}>I've saved them</button>
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
      <label htmlFor="tfa-password">Current password</label>
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
  const cancel = <button type="button" className="btn btn-secondary" onClick={() => go(null)}>Cancel</button>;

  let body;
  if (status === null) body = <Spinner />;
  else if (step === "codes") body = <RecoveryCodes codes={codes} onDone={finish} />;
  else if (step === "password" || step === "regenerate") body = (
    <form onSubmit={step === "password" ? start : regenerate} className="tfa-form" noValidate>
      {step === "regenerate" && <p className="account-help">Your current recovery codes will stop working.</p>}
      {passwordField}
      <div className="btn-group">
        <button className="btn btn-primary" type="submit" disabled={busy || !password}>
          {step === "password" ? "Continue" : "Get new codes"}
        </button>
        {cancel}
      </div>
    </form>
  );
  else if (step === "scan") body = (
    <form onSubmit={enable} className="tfa-form" noValidate>
      <p className="account-help">
        Scan this with an authenticator app (Google Authenticator, Microsoft Authenticator, 1Password, Authy…),
        then enter the 6-digit code it shows.
      </p>
      <div className="tfa-qr">
        <img src={enrolment.qr} alt="QR code for your authenticator app" width="200" height="200" />
        <div className="account-help">
          Can't scan? Enter this key: <code className="tfa-secret">{enrolment.secret.match(/.{1,4}/g).join(" ")}</code>
        </div>
      </div>
      {codeField("Code from the app")}
      <div className="btn-group">
        <button className="btn btn-primary" type="submit" disabled={busy || !/^\d{6}$/.test(code.trim())}>Turn on</button>
        {cancel}
      </div>
    </form>
  );
  else if (step === "disable") body = (
    <form onSubmit={disable} className="tfa-form" noValidate>
      {passwordField}
      {codeField("Authenticator or recovery code")}
      <div className="btn-group">
        <button className="btn btn-danger" type="submit" disabled={busy || !password || code.trim().length < 6}>Turn off</button>
        {cancel}
      </div>
    </form>
  );
  else if (status.enabled) body = (
    <>
      <p className="account-help">
        On. Signing in needs a code from your authenticator app.{" "}
        {status.recovery_codes_left} recovery code{status.recovery_codes_left === 1 ? "" : "s"} left.
      </p>
      <div className="btn-group">
        <button className="btn btn-secondary btn-sm" onClick={() => go("regenerate")}>New recovery codes</button>
        <button className="btn btn-danger btn-sm" onClick={() => go("disable")}>Turn off</button>
      </div>
    </>
  );
  else body = (
    <>
      <p className="account-help">
        Off. Add a code from an authenticator app to your sign-in, so a stolen password isn't enough.
      </p>
      <div><button className="btn btn-primary btn-sm" onClick={() => go("password")}>Turn on</button></div>
    </>
  );

  return (
    <div className="card account-card">
      <div className="account-users-head">
        <div className="section-title">Two-factor authentication</div>
        {status && <span className={`tag ${status.enabled ? "tag-on" : ""}`}>{status.enabled ? "on" : "off"}</span>}
      </div>
      {error && <div className="auth-error" role="alert">{error}</div>}
      {body}
    </div>
  );
}

function describeAgent(ua) {
  if (!ua) return "Unknown device";
  const browser = /Edg\//.test(ua) ? "Edge" : /Firefox\//.test(ua) ? "Firefox" : /Chrome\//.test(ua) ? "Chrome"
    : /Safari\//.test(ua) ? "Safari" : /curl|python|httpx/i.test(ua) ? "API client" : "Browser";
  const os = /Windows/.test(ua) ? "Windows" : /Mac OS X/.test(ua) ? "macOS" : /Android/.test(ua) ? "Android"
    : /iPhone|iPad/.test(ua) ? "iOS" : /Linux/.test(ua) ? "Linux" : "";
  return os ? `${browser} on ${os}` : browser;
}

function Sessions() {
  const { toast } = useStore();
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
    if (!confirm("Sign out every other browser and device?")) return;
    try { toast((await api.endMyOtherSessions()).message, "success"); load(); }
    catch (err) { toast(err.message, "error"); }
  };

  const others = (sessions || []).filter((s) => !s.current).length;
  return (
    <div className="card account-card account-sessions">
      <div className="account-users-head">
        <div className="section-title">Active sessions</div>
        <button className="btn btn-secondary btn-sm" onClick={endOthers} disabled={!others}>Sign out all others</button>
      </div>
      <p className="account-help">Browsers and devices signed in to your account.</p>
      {sessions === null ? <Spinner /> : (
        <ul className="session-list">
          {sessions.map((s) => (
            <li key={s.id} className="session-row">
              <div>
                <div className="session-device">
                  {describeAgent(s.user_agent)}{s.current && <span className="tag">this browser</span>}
                </div>
                <div className="account-help">
                  {s.ip || "unknown IP"} · active {formatDate(s.last_seen_at)} · signed in {formatDate(s.created_at)}
                </div>
              </div>
              {!s.current && <button className="btn btn-sm btn-secondary" onClick={() => end(s)}>Sign out</button>}
            </li>
          ))}
        </ul>
      )}
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
    <Modal title="Add user" onClose={onClose}>
      <form className="account-modal-form" onSubmit={submit} noValidate>
        {error && <div className="auth-error" role="alert">{error}</div>}
        <div className="field">
          <label htmlFor="nu-username">Username</label>
          <input id="nu-username" className="input" autoComplete="off" autoFocus value={form.username}
            onChange={(e) => setForm({ ...form, username: e.target.value })} />
          <span className="auth-hint">3–32 characters: letters, numbers, dot, dash, underscore.</span>
        </div>
        <div className="field">
          <label htmlFor="nu-password">Password</label>
          <input id="nu-password" className="input" type="password" autoComplete="new-password" value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="nu-confirm">Confirm password</label>
          <input id="nu-confirm" className="input" type="password" autoComplete="new-password" value={form.confirm}
            onChange={(e) => setForm({ ...form, confirm: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="nu-role">Role</label>
          <select id="nu-role" className="select" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
            {ROLES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
          </select>
          <span className="auth-hint">{ROLES.find((r) => r.value === form.role)?.help}</span>
        </div>
        <div className="btn-group">
          <button className="btn btn-primary" type="submit" disabled={busy || !form.username.trim() || !form.password}>
            {busy ? "Creating…" : "Create user"}
          </button>
          <button className="btn btn-secondary" type="button" onClick={onClose}>Cancel</button>
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
    <Modal title={`Reset password for ${user.username}`} onClose={onClose}>
      <form className="account-modal-form" onSubmit={submit} noValidate>
        <p className="account-help">They'll be signed out everywhere and need the new password to sign in.</p>
        {error && <div className="auth-error" role="alert">{error}</div>}
        <div className="field">
          <label htmlFor="rp-password">New password</label>
          <input id="rp-password" className="input" type="password" autoComplete="new-password" autoFocus value={password}
            onChange={(e) => setPassword(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="rp-confirm">Confirm new password</label>
          <input id="rp-confirm" className="input" type="password" autoComplete="new-password" value={confirm}
            onChange={(e) => setConfirm(e.target.value)} />
        </div>
        <div className="btn-group">
          <button className="btn btn-primary" type="submit" disabled={busy || !password}>
            {busy ? "Saving…" : "Reset password"}
          </button>
          <button className="btn btn-secondary" type="button" onClick={onClose}>Cancel</button>
        </div>
      </form>
    </Modal>
  );
}

function Users() {
  const { user: me } = useAuth();
  const { toast } = useStore();
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
    if (!confirm(`Sign "${u.username}" out of every browser and device?`)) return;
    try { toast((await api.endUserSessions(u.id)).message, "success"); }
    catch (err) { toast(err.message, "error"); }
  };

  const resetTwoFactor = async (u) => {
    if (!confirm(`Turn off two-factor authentication for "${u.username}"? Use this when they've lost `
      + "their authenticator and recovery codes. They'll be signed out and can set it up again.")) return;
    try { toast((await api.resetUserTwoFactor(u.id)).message, "success"); load(); }
    catch (err) { toast(err.message, "error"); }
  };

  const remove = async (u) => {
    if (!confirm(`Delete user "${u.username}"? They'll be signed out immediately.`)) return;
    try {
      const res = await api.deleteUser(u.id);
      toast(res.message, "success");
      load();
    } catch (err) { toast(err.message, "error"); }
  };

  const columns = [
    { key: "username", label: "Username", render: (u) => (
      <span className="account-username">
        {u.username}{u.id === me.id && <span className="tag">you</span>}{u.sso && <span className="tag">SSO</span>}
      </span>
    )},
    { key: "role", label: "Role", render: (u) => u.id === me.id ? <Pill status={u.role} /> : (
      <select className="select account-role-select" value={u.role} aria-label={`Role of ${u.username}`}
        onChange={(e) => changeRole(u, e.target.value)}>
        {ROLES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
      </select>
    )},
    { key: "totp_enabled", label: "2FA", render: (u) => u.sso ? <span className="account-help">via SSO</span> : (
      <span className={`tag ${u.totp_enabled ? "tag-on" : ""}`}>{u.totp_enabled ? "on" : "off"}</span>
    )},
    { key: "last_login_at", label: "Last sign-in", render: (u) => formatDate(u.last_login_at) },
    { key: "created_at", label: "Created", render: (u) => new Date(u.created_at).toLocaleDateString() },
    { key: "actions", label: "", render: (u) => u.id === me.id ? (
      <span className="account-help">{me.sso ? "" : "Use “Change password” above"}</span>
    ) : (
      <div className="btn-group">
        {!u.sso && <button className="btn btn-sm btn-secondary" onClick={() => setResetting(u)}>Reset password</button>}
        <button className="btn btn-sm btn-secondary" onClick={() => signOutEverywhere(u)}>Sign out everywhere</button>
        {u.totp_enabled && <button className="btn btn-sm btn-secondary" onClick={() => resetTwoFactor(u)}>Reset 2FA</button>}
        <button className="btn btn-sm btn-danger" onClick={() => remove(u)}>Delete</button>
      </div>
    )},
  ];

  return (
    <div className="section">
      <div className="account-users-head">
        <div className="section-title">Users</div>
        <button className="btn btn-primary btn-sm" onClick={() => setAdding(true)}>Add user</button>
      </div>
      {users === null ? <Spinner /> : <DataTable columns={columns} rows={users} emptyMsg="No users" />}
      {adding && <AddUserModal onClose={() => setAdding(false)} onCreated={() => { setAdding(false); load(); }} />}
      {resetting && <ResetPasswordModal user={resetting} onClose={() => setResetting(null)} />}
    </div>
  );
}

export default function Account() {
  const { user } = useAuth();
  return (
    <>
      <PageHeader
        title="Account"
        subtitle={user.is_admin ? "Your sign-in security and who can sign in" : "Your sign-in security"}
      />
      <div className="section">
        <div className="account-me">
          Signed in as <strong>{user.username}</strong>
          <Pill status={user.role} />
        </div>
        <div className="account-grid">
          {user.sso ? (
            <div className="card account-card">
              <div className="section-title">Single sign-on</div>
              <p className="account-help">
                You sign in through your organization's identity provider. Change your password and
                two-factor settings there.
              </p>
            </div>
          ) : (
            <>
              <ChangePassword />
              <TwoFactor />
            </>
          )}
          <Sessions />
        </div>
      </div>
      {user.is_admin && <Users />}
    </>
  );
}
