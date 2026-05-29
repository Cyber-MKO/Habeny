import { Routes, Route, NavLink, useLocation } from "react-router-dom";
import { useMetricsSocket } from "./ws";
import { useStore } from "./store";

import Dashboard from "./pages/Dashboard";
import Agents from "./pages/Agents";
import Deploy from "./pages/Deploy";
import Groups from "./pages/Groups";
import BulkOps from "./pages/BulkOps";
import LogUpload from "./pages/LogUpload";
import Simulations from "./pages/Simulations";
import SiemStats from "./pages/SiemStats";
import Reports from "./pages/Reports";
import Activity from "./pages/Activity";
import Configs from "./pages/Configs";
import SystemInfo from "./pages/SystemInfo";
import Managers from "./pages/Managers";
import SyslogConfigs from "./pages/SyslogConfigs";
import Benchmarks from "./pages/Benchmarks";
import BenchmarkRunner from "./pages/BenchmarkRunner";

const NAV = [
  { to: "/", label: "Dashboard", icon: "M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-4 0h4" },
  { to: "/system", label: "System", icon: "M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" },
  { to: "/managers", label: "Managers", icon: "M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z" },
  { to: "/agents", label: "Containers", icon: "M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2" },
  { to: "/deploy", label: "Deploy", icon: "M12 4v16m8-8H4" },
  { to: "/groups", label: "Groups", icon: "M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" },
  { to: "/bulk", label: "Bulk Ops", icon: "M4 6h16M4 12h16M4 18h16" },
  { to: "/logs", label: "Log Upload", icon: "M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" },
  { to: "/syslog-config", label: "Syslog Config", icon: "M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" },
  { to: "/simulations", label: "Simulations", icon: "M13 10V3L4 14h7v7l9-11h-7z" },
  { to: "/benchmark-runner", label: "Benchmark Runner", icon: "M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" },
  { to: "/benchmarks", label: "Perf Metrics", icon: "M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" },
  { to: "/siem", label: "SIEM Stats", icon: "M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" },
  { to: "/reports", label: "Reports", icon: "M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" },
  { to: "/configs", label: "Configs", icon: "M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z M15 12a3 3 0 11-6 0 3 3 0 016 0z" },
  { to: "/activity", label: "Activity", icon: "M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" },
];

function Icon({ d }) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d={d} />
    </svg>
  );
}

function Toasts() {
  const { toasts, dismissToast } = useStore();
  if (!toasts.length) return null;
  return (
    <div className="toast-container">
      {toasts.map((t) => (
        <div key={t.id} className={`toast toast-${t.variant}`} onClick={() => dismissToast(t.id)}>
          {t.message}
        </div>
      ))}
    </div>
  );
}

const TITLES = { "/": "Dashboard", "/system": "System Info", "/managers": "Managers", "/agents": "Containers", "/deploy": "Deploy", "/groups": "Groups", "/bulk": "Bulk Operations", "/logs": "Log Upload", "/syslog-config": "Syslog Config", "/simulations": "Simulations", "/benchmark-runner": "Benchmark Runner", "/benchmarks": "Perf Metrics", "/siem": "SIEM Stats", "/reports": "Reports", "/configs": "Configs", "/activity": "Activity Log" };

export default function App() {
  const { connected } = useMetricsSocket();
  const location = useLocation();
  const title = TITLES[location.pathname] || "Habeny";

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <h1>Habeny</h1>
          <p>Multi-SIEM Container Platform</p>
        </div>
        <nav className="sidebar-nav">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.to === "/"} className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
              <Icon d={n.icon} />
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-footer">v2.0.0</div>
      </aside>

      <div className="main-area">
        <header className="header">
          <span className="header-title">{title}</span>
          <div className="ws-badge">
            <span className={`ws-dot${connected ? " on" : ""}`} />
            {connected ? "Live" : "Disconnected"}
          </div>
        </header>

        <div className="content">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/system" element={<SystemInfo />} />
            <Route path="/managers" element={<Managers />} />
            <Route path="/agents" element={<Agents />} />
            <Route path="/deploy" element={<Deploy />} />
            <Route path="/groups" element={<Groups />} />
            <Route path="/bulk" element={<BulkOps />} />
            <Route path="/logs" element={<LogUpload />} />
            <Route path="/syslog-config" element={<SyslogConfigs />} />
            <Route path="/simulations" element={<Simulations />} />
            <Route path="/benchmark-runner" element={<BenchmarkRunner />} />
            <Route path="/benchmarks" element={<Benchmarks />} />
            <Route path="/siem" element={<SiemStats />} />
            <Route path="/reports" element={<Reports />} />
            <Route path="/configs" element={<Configs />} />
            <Route path="/activity" element={<Activity />} />
          </Routes>
        </div>
      </div>

      <Toasts />
    </div>
  );
}
