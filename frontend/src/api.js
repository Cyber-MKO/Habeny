const BASE = import.meta.env.VITE_API_URL || "/api";

async function request(path, opts = {}) {
  const { method = "GET", body, params } = opts;
  let url = `${BASE}${path}`;
  if (params) {
    const qs = new URLSearchParams(params).toString();
    if (qs) url += `?${qs}`;
  }
  const init = { method, headers: { "Content-Type": "application/json" } };
  if (body) init.body = JSON.stringify(body);
  const res = await fetch(url, init);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || err.error || res.statusText);
  }
  return res.json();
}

export const api = {
  get: (p, params) => request(p, { params }),
  post: (p, body) => request(p, { method: "POST", body }),
  del: (p) => request(p, { method: "DELETE" }),

  getHealth: () => request("/system/health"),
  getSystemInfo: () => request("/system/info"),
  getAgents: (params) => request("/agents", { params }),
  getAgent: (id) => request(`/agents/${id}`),
  getAgentsStats: () => request("/agents/stats"),
  deploy: (body) => request("/agents/deploy", { method: "POST", body }),
  startAgent: (id) => request(`/agents/${id}/start`, { method: "POST" }),
  stopAgent: (id) => request(`/agents/${id}/stop`, { method: "POST" }),
  deleteAgent: (id) => request(`/agents/${id}`, { method: "DELETE" }),
  bulkOp: (op, body) => request(`/agents/bulk/${op}`, { method: "POST", body }),

  getGroups: () => request("/groups"),
  createGroup: (body) => request("/groups", { method: "POST", body }),
  deleteGroup: (name) => request(`/groups/${name}`, { method: "DELETE" }),
  assignGroup: (name, body) => request(`/groups/${name}/assign`, { method: "POST", body }),
  removeGroup: (name, body) => request(`/groups/${name}/remove`, { method: "POST", body }),

  getSimulations: () => request("/simulations"),
  startSimulation: (body) => request("/simulations/start", { method: "POST", body }),
  loadSimulation: (body) => request("/simulations/load", { method: "POST", body }),
  startSyslog: (body) => request("/simulations/syslog/start", { method: "POST", body }),
  stopSimulation: (id) => request(`/simulations/${id}/stop`, { method: "POST" }),

  getConfigs: () => request("/configs"),
  importConfig: (body) => request("/configs/import", { method: "POST", body }),
  exportConfig: (id) => request(`/configs/export/${id}`),

  generateReport: (body) => request("/reports/generate", { method: "POST", body }),
  getReport: (id) => request(`/reports/${id}`),

  getActivity: (params) => request("/activity/logs", { params }),
  getSiemStats: (type) => request(`/siem/${type}/stats`),

  uploadLogs: (id, body) => request(`/agents/${id}/logs/upload`, { method: "POST", body }),

  getBenchmarks: (params) => request("/metrics/benchmarks", { params }),
  getBenchmarkScenarios: () => request("/benchmarks/scenarios"),
  startBenchmark: (body) => request("/benchmarks/start", { method: "POST", body }),
  stopBenchmark: (id) => request(`/benchmarks/${id}/stop`, { method: "POST" }),
  listBenchmarks: () => request("/benchmarks"),
  getBenchmark: (id) => request(`/benchmarks/${id}`),
  getBenchmarkMetrics: (id, params) => request(`/benchmarks/${id}/metrics`, { params }),
  getBenchmarkBottlenecks: (id) => request(`/benchmarks/${id}/bottlenecks`),
  compareBenchmarks: (ids) => request("/benchmarks/compare", { method: "POST", body: { benchmark_ids: ids } }),
  getMetricsHistory: (params) => request("/metrics/history", { params }),
  getSystemMetrics: () => request("/metrics/system"),

  getSyslogConfigs: () => request("/syslog-configs"),
  createSyslogConfig: (body) => request("/syslog-configs", { method: "POST", body }),
  updateSyslogConfig: (id, body) => request(`/syslog-configs/${id}`, { method: "PUT", body }),
  deleteSyslogConfig: (id) => request(`/syslog-configs/${id}`, { method: "DELETE" }),
  testSyslogConnectivity: (params) => request("/syslog-configs/test-connectivity", { params }),
  enableUtmSyslog: (id, protocol) => request(`/agents/${id}/enable-syslog?protocol=${protocol}`, { method: "POST" }),
  disableUtmSyslog: (id, protocol) => request(`/agents/${id}/disable-syslog?protocol=${protocol}`, { method: "POST" }),

  getManagers: () => request("/managers"),
  getManager: (id) => request(`/managers/${id}`),
  createManager: (body) => request("/managers", { method: "POST", body }),
  updateManager: (id, body) => request(`/managers/${id}`, { method: "PUT", body }),
  deleteManager: (id) => request(`/managers/${id}`, { method: "DELETE" }),
};
