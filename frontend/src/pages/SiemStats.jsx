import { useEffect, useState, useCallback } from "react";
import { api } from "../api";
import { useMetricsSocket } from "../ws";
import { useStore } from "../store";
import { PageHeader, StatCard, Spinner } from "../components/UI";

const SIEM_TYPES = ["wazuh", "ossec", "ossim", "utmstack", "elastic"];

export default function SiemStats() {
  const { toast } = useStore();
  const { metrics } = useMetricsSocket();
  const [stats, setStats] = useState({});
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const results = {};
    await Promise.all(
      SIEM_TYPES.map(async (type) => {
        try {
          const res = await api.getSiemStats(type);
          results[type] = res.data || {};
        } catch {
          results[type] = {};
        }
      })
    );
    setStats(results);
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  if (loading) return <Spinner />;

  return (
    <>
      <PageHeader title="SIEM Stats" subtitle="Connectivity and agent counts per SIEM type">
        <button className="btn btn-secondary" onClick={load}>Refresh</button>
      </PageHeader>

      <div className="stats-grid">
        {SIEM_TYPES.map((type) => {
          const s = stats[type] || {};
          const live = metrics?.siem_stats?.[type];
          const total = live?.total_agents ?? s.total_agents ?? 0;
          const connected = live?.connected_agents ?? s.connected_agents ?? 0;
          const rate = live?.connection_rate ?? s.connection_rate ?? 0;
          return (
            <StatCard
              key={type}
              label={type.charAt(0).toUpperCase() + type.slice(1)}
              value={total}
              color={total > 0 ? "blue" : undefined}
              meta={`Connected: ${connected} · Rate: ${rate}%`}
            />
          );
        })}
      </div>
    </>
  );
}
