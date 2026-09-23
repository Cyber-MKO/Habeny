import { useState } from "react";
import { useAuth } from "../auth";

export default function Login() {
  const { setupRequired, expired, login, setup } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [setupToken, setSetupToken] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    if (setupRequired) {
      if (password.length < 12) return setError("Password must be at least 12 characters.");
      if (password !== confirm) return setError("Passwords don't match.");
    }
    setBusy(true);
    try {
      if (setupRequired) await setup(username.trim(), password, setupToken.trim());
      else await login(username.trim(), password);
    } catch (err) {
      setError(err.message);
      setPassword("");
      setConfirm("");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth-page">
      <form className="auth-card" onSubmit={handleSubmit} noValidate>
        <div className="auth-brand">
          <div className="brand-wordmark">
            habeny<span className="brand-cursor" aria-hidden="true" />
          </div>
          <p>Multi-SIEM Container Platform</p>
        </div>

        <h1 className="auth-title">{setupRequired ? "Create the admin account" : "Sign in"}</h1>
        <p className="auth-subtitle">
          {setupRequired
            ? "No account exists yet. To prove you control this server, enter the setup token it generated."
            : "Sign in to manage containers, simulations and reports."}
        </p>

        {expired && !error && <div className="auth-notice">Your session has expired. Sign in again.</div>}
        {error && <div className="auth-error" role="alert">{error}</div>}

        {setupRequired && (
          <div className="field">
            <label htmlFor="auth-setup-token">Setup token</label>
            <input
              id="auth-setup-token"
              className="input"
              autoComplete="off"
              spellCheck={false}
              required
              value={setupToken}
              onChange={(e) => setSetupToken(e.target.value)}
            />
            <span className="auth-hint">
              On the server: <code>sudo cat /var/lib/lxc-siem-platform/setup-token</code> or{" "}
              <code>journalctl -u habeny | grep "setup token"</code>
            </span>
          </div>
        )}
        <div className="field">
          <label htmlFor="auth-username">Username</label>
          <input
            id="auth-username"
            className="input"
            autoComplete="username"
            autoFocus={!setupRequired}
            required
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="auth-password">Password</label>
          <input
            id="auth-password"
            className="input"
            type="password"
            autoComplete={setupRequired ? "new-password" : "current-password"}
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {setupRequired && <span className="auth-hint">At least 12 characters; not a common password.</span>}
        </div>
        {setupRequired && (
          <div className="field">
            <label htmlFor="auth-confirm">Confirm password</label>
            <input
              id="auth-confirm"
              className="input"
              type="password"
              autoComplete="new-password"
              required
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
            />
          </div>
        )}

        <button className="btn btn-primary auth-submit" type="submit" disabled={busy || !username.trim() || !password || (setupRequired && !setupToken.trim())}>
          {busy ? (setupRequired ? "Creating account…" : "Signing in…") : setupRequired ? "Create account" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
