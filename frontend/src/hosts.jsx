import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, setApiHost } from "./api";
import { t } from "./i18n";

const STORAGE_KEY = "habeny.host";
const HostCtx = createContext({ hosts: [], hostId: null, host: null, selectHost: () => {}, refreshHosts: () => {} });

function storedHost() {
  try { return Number(localStorage.getItem(STORAGE_KEY)) || null; } catch { return null; }
}

// Which Habeny server the console is working on: this one (null) or a registered host.
// Children are re-mounted on a switch, so every page loads the new server's data.
export function HostProvider({ children }) {
  const [hosts, setHosts] = useState([]);
  const [hostId, setHostId] = useState(() => {
    const id = storedHost();
    setApiHost(id);
    return id;
  });

  const selectHost = useCallback((id) => {
    const value = id ? Number(id) : null;
    setApiHost(value);
    try {
      if (value) localStorage.setItem(STORAGE_KEY, String(value));
      else localStorage.removeItem(STORAGE_KEY);
    } catch { /* remembered for this page only */ }
    setHostId(value);
  }, []);

  const refreshHosts = useCallback(async () => {
    try {
      const list = (await api.getHosts()).data.hosts;
      setHosts(list);
      if (storedHost() && !list.some((h) => h.id === storedHost())) selectHost(null); // removed meanwhile
    } catch { setHosts([]); }
  }, [selectHost]);

  useEffect(() => { refreshHosts(); }, [refreshHosts]);

  const host = hosts.find((h) => h.id === hostId) || null;
  return (
    <HostCtx.Provider value={{ hosts, hostId, host, selectHost, refreshHosts }}>
      <div key={hostId || "local"} className="host-scope">{children}</div>
    </HostCtx.Provider>
  );
}

export const useHosts = () => useContext(HostCtx);

export function HostSwitcher() {
  const { hosts, hostId, selectHost } = useHosts();
  if (!hosts.length) return null;
  return (
    <div className="host-switcher">
      <label htmlFor="host-switch">{t("Server")}</label>
      <select id="host-switch" className="select" value={hostId || ""} onChange={(e) => selectHost(e.target.value)}>
        <option value="">{t("This server")}</option>
        {hosts.map((h) => <option key={h.id} value={h.id}>{h.name}{h.last_status === "error" ? t(" (unreachable)") : ""}</option>)}
      </select>
    </div>
  );
}
