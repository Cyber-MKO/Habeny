import { useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { t } from "../i18n";
import LanguagePicker from "../components/LanguagePicker";

// A failed single sign-on comes back as /?sso_error=...; show it once and tidy the URL
function takeSsoError() {
  const params = new URLSearchParams(window.location.search);
  const message = params.get("sso_error");
  if (message) window.history.replaceState(null, "", window.location.pathname);
  return message;
}

function SecondFactor({ mfaToken, onCancel }) {
  const { loginSecondFactor } = useAuth();
  const [code, setCode] = useState("");
  const [useRecovery, setUseRecovery] = useState(false);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await loginSecondFactor(mfaToken, code.trim());
    } catch (err) {
      if (err.message.startsWith("Sign-in expired")) return onCancel(err.message);
      setError(err.message);
      setCode("");
      setBusy(false);
    }
  };

  const valid = useRecovery ? code.replace(/[^a-z0-9]/gi, "").length === 10 : /^\d{6}$/.test(code.trim());
  return (
    <form className="auth-card" onSubmit={handleSubmit} noValidate>
      <div className="auth-brand">
        <div className="brand-wordmark">
          habeny<span className="brand-cursor" aria-hidden="true" />
        </div>
        <p>{t("Multi-SIEM Container Platform")}</p>
      </div>
      <h1 className="auth-title">{t("Two-factor authentication")}</h1>
      <p className="auth-subtitle">
        {useRecovery
          ? t("Enter one of the recovery codes you saved when you turned on two-factor. Each works once.")
          : t("Enter the 6-digit code from your authenticator app.")}
      </p>
      {error && <div className="auth-error" role="alert">{error}</div>}
      <div className="field">
        <label htmlFor="auth-code">{useRecovery ? t("Recovery code") : t("Authentication code")}</label>
        <input
          id="auth-code"
          key={useRecovery ? "recovery" : "totp"}
          className="input auth-code-input"
          autoComplete="one-time-code"
          inputMode={useRecovery ? "text" : "numeric"}
          maxLength={useRecovery ? 11 : 6}
          placeholder={useRecovery ? t("xxxxx-xxxxx") : "123456"}
          autoFocus
          spellCheck={false}
          value={code}
          onChange={(e) => setCode(e.target.value)}
        />
      </div>
      <button className="btn btn-primary auth-submit" type="submit" disabled={busy || !valid}>
        {busy ? t("Verifying…") : t("Verify")}
      </button>
      <div className="auth-links">
        <button type="button" className="link-btn" onClick={() => { setUseRecovery(!useRecovery); setCode(""); setError(null); }}>
          {useRecovery ? t("Use an authenticator code") : t("Use a recovery code")}
        </button>
        <button type="button" className="link-btn" onClick={() => onCancel(null)}>{t("Back")}</button>
      </div>
    </form>
  );
}

export default function Login() {
  const { setupRequired, expired, sso, login, setup } = useAuth();
  const [mfaToken, setMfaToken] = useState(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [setupToken, setSetupToken] = useState("");
  const [error, setError] = useState(takeSsoError);
  const [busy, setBusy] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    if (setupRequired) {
      if (password.length < 12) return setError(t("Password must be at least 12 characters."));
      if (password !== confirm) return setError(t("Passwords don't match."));
    }
    setBusy(true);
    try {
      if (setupRequired) await setup(username.trim(), password, setupToken.trim());
      else {
        const result = await login(username.trim(), password);
        if (result.mfaToken) {
          setPassword("");
          setMfaToken(result.mfaToken);
        }
      }
    } catch (err) {
      setError(err.message);
      setPassword("");
      setConfirm("");
    } finally {
      setBusy(false);
    }
  };

  if (mfaToken) {
    return (
      <main className="auth-page">
        <SecondFactor mfaToken={mfaToken} onCancel={(message) => { setMfaToken(null); setError(message); }} />
      </main>
    );
  }

  return (
    <main className="auth-page">
      <form className="auth-card" onSubmit={handleSubmit} noValidate>
        <div className="auth-brand">
          <div className="brand-wordmark">
            habeny<span className="brand-cursor" aria-hidden="true" />
          </div>
          <p>{t("Multi-SIEM Container Platform")}</p>
        </div>

        <h1 className="auth-title">{setupRequired ? t("Create the admin account") : t("Sign in")}</h1>
        <p className="auth-subtitle">
          {setupRequired
            ? t("No account exists yet. To prove you control this server, enter the setup token it generated.")
            : t("Sign in to manage containers, simulations and reports.")}
        </p>

        {expired && !error && <div className="auth-notice">{t("Your session has expired. Sign in again.")}</div>}
        {error && <div className="auth-error" role="alert">{error}</div>}

        {setupRequired && (
          <div className="field">
            <label htmlFor="auth-setup-token">{t("Setup token")}</label>
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
              {t("On the server:")} <code>sudo cat /var/lib/lxc-siem-platform/setup-token</code> {t("or")}{" "}
              <code>journalctl -u habeny | grep "setup token"</code>
            </span>
          </div>
        )}
        <div className="field">
          <label htmlFor="auth-username">{t("Username")}</label>
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
          <label htmlFor="auth-password">{t("Password")}</label>
          <input
            id="auth-password"
            className="input"
            type="password"
            autoComplete={setupRequired ? "new-password" : "current-password"}
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {setupRequired && <span className="auth-hint">{t("At least 12 characters; not a common password.")}</span>}
        </div>
        {setupRequired && (
          <div className="field">
            <label htmlFor="auth-confirm">{t("Confirm password")}</label>
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
          {busy ? (setupRequired ? t("Creating account…") : t("Signing in…")) : setupRequired ? t("Create account") : t("Sign in")}
        </button>
        {!setupRequired && sso?.enabled && (
          <>
            <div className="auth-divider"><span>{t("or")}</span></div>
            <a className="btn btn-secondary auth-submit" href={api.ssoLoginUrl}>{sso.label}</a>
          </>
        )}
      </form>
      <LanguagePicker compact />
    </main>
  );
}
