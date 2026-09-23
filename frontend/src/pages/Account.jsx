import { useCallback, useEffect, useState } from "react";
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
      <span className="account-username">{u.username}{u.id === me.id && <span className="tag">you</span>}</span>
    )},
    { key: "role", label: "Role", render: (u) => u.id === me.id ? <Pill status={u.role} /> : (
      <select className="select account-role-select" value={u.role} aria-label={`Role of ${u.username}`}
        onChange={(e) => changeRole(u, e.target.value)}>
        {ROLES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
      </select>
    )},
    { key: "last_login_at", label: "Last sign-in", render: (u) => formatDate(u.last_login_at) },
    { key: "created_at", label: "Created", render: (u) => new Date(u.created_at).toLocaleDateString() },
    { key: "actions", label: "", render: (u) => u.id === me.id ? (
      <span className="account-help">Use “Change password” above</span>
    ) : (
      <div className="btn-group">
        <button className="btn btn-sm btn-secondary" onClick={() => setResetting(u)}>Reset password</button>
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
        subtitle={user.is_admin ? "Your password and who can sign in" : "Your password"}
      />
      <div className="section">
        <div className="account-me">
          Signed in as <strong>{user.username}</strong>
          <Pill status={user.role} />
        </div>
        <ChangePassword />
      </div>
      {user.is_admin && <Users />}
    </>
  );
}
