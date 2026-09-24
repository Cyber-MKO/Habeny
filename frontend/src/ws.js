import { createContext, createElement, useContext, useEffect, useRef, useState } from "react";

function useMetricsConnection() {
  const [metrics, setMetrics] = useState(null);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef(null);
  const retryRef = useRef(0);
  const timerRef = useRef(null);

  useEffect(() => {
    let stopped = false; // this effect's lifetime: after cleanup, don't reconnect
    const connect = () => {
      const proto = window.location.protocol === "https:" ? "wss" : "ws";
      const base = import.meta.env.VITE_API_URL
        ? new URL(import.meta.env.VITE_API_URL).host
        : window.location.host;
      const ws = new WebSocket(`${proto}://${base}/ws/metrics`);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        retryRef.current = 0;
      };
      ws.onmessage = (event) => {
        try {
          setMetrics(JSON.parse(event.data));
        } catch { /* ignore a malformed message; the next one replaces it */ }
      };
      ws.onclose = () => {
        setConnected(false);
        wsRef.current = null;
        if (stopped) return;
        const delay = Math.min(1000 * 2 ** retryRef.current, 30000);
        retryRef.current += 1;
        timerRef.current = setTimeout(connect, delay);
      };
      ws.onerror = () => ws.close();
    };

    connect();
    return () => {
      stopped = true;
      clearTimeout(timerRef.current);
      if (wsRef.current) wsRef.current.close();
    };
  }, []);

  return { metrics, connected };
}

const MetricsCtx = createContext({ metrics: null, connected: false });

// One /ws/metrics connection for the whole signed-in app; every page reads from it
// instead of opening its own socket (each socket costs a metrics collection every 5 s).
export function MetricsProvider({ children }) {
  const value = useMetricsConnection();
  return createElement(MetricsCtx.Provider, { value }, children);
}

export function useMetricsSocket() {
  return useContext(MetricsCtx);
}
