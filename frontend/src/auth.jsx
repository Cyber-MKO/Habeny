import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, UNAUTHORIZED_EVENT } from "./api";

const AuthCtx = createContext(null);

export function AuthProvider({ children }) {
  // status: "loading" | "ready" | "error"
  const [state, setState] = useState({ status: "loading", setupRequired: false, user: null, error: null });

  const refresh = useCallback(async () => {
    try {
      const res = await api.authStatus();
      setState({ status: "ready", setupRequired: res.data.setup_required, user: res.data.user, error: null });
    } catch (err) {
      setState((s) => ({ ...s, status: "error", error: err.message }));
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  // Any API call that comes back 401 (e.g. the session expired) drops back to the sign-in page
  useEffect(() => {
    const onUnauthorized = () => setState((s) => (s.user ? { ...s, user: null, expired: true } : s));
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, []);

  const login = useCallback(async (username, password) => {
    const res = await api.login({ username, password });
    setState({ status: "ready", setupRequired: false, user: res.data.user, error: null });
  }, []);

  const setup = useCallback(async (username, password) => {
    const res = await api.setupAdmin({ username, password });
    setState({ status: "ready", setupRequired: false, user: res.data.user, error: null });
  }, []);

  const logout = useCallback(async () => {
    try { await api.logout(); } catch { /* signed out locally either way */ }
    setState((s) => ({ ...s, user: null, expired: false }));
  }, []);

  return <AuthCtx.Provider value={{ ...state, refresh, login, setup, logout }}>{children}</AuthCtx.Provider>;
}

export const useAuth = () => useContext(AuthCtx);
