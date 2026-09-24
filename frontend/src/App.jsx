import { useEffect, useState } from "react";
import { Routes, Route, NavLink, useLocation } from "react-router-dom";
import { MetricsProvider, useMetricsSocket } from "./ws";
import { useStore } from "./store";
import { Modal, Spinner } from "./components/UI";
import { useAuth } from "./auth";
import Login from "./pages/Login";

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
import Account from "./pages/Account";
import Monitoring from "./pages/Monitoring";
import Notifications from "./pages/Notifications";
import Teams from "./pages/Teams";
import { api } from "./api";

const NAV = [
  {
    section: "Overview",
    items: [
      { to: "/", label: "Dashboard", icon: "M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-4 0h4" },
      { to: "/system", label: "System", icon: "M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" },
      { to: "/activity", label: "Activity", icon: "M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" },
      { to: "/monitoring", label: "Monitoring", icon: "M3.75 3v11.25A2.25 2.25 0 006 16.5h2.25M3.75 3h-1.5m1.5 0h16.5m0 0h1.5m-1.5 0v11.25A2.25 2.25 0 0118 16.5h-2.25m-7.5 0h7.5m-7.5 0l-1 3m8.5-3l1 3m0 0l.5 1.5m-.5-1.5h-9.5m0 0l-.5 1.5M9 11.25v1.5M12 9v3.75m3-6v6" },
    ],
  },
  {
    section: "Fleet",
    items: [
      { to: "/agents", label: "Containers", icon: "M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2" },
      { to: "/deploy", label: "Deploy", minRole: "operator", icon: "M12 4v16m8-8H4" },
      { to: "/groups", label: "Groups", icon: "M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" },
      { to: "/bulk", label: "Bulk Ops", minRole: "operator", icon: "M4 6h16M4 12h16M4 18h16" },
      { to: "/managers", label: "Managers", icon: "M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z" },
    ],
  },
  {
    section: "Testing",
    items: [
      { to: "/simulations", label: "Simulations", icon: "M13 10V3L4 14h7v7l9-11h-7z" },
      { to: "/logs", label: "Log Upload", minRole: "operator", icon: "M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" },
      { to: "/syslog-config", label: "Syslog Config", icon: "M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" },
      { to: "/benchmark-runner", label: "Benchmark Runner", minRole: "operator", icon: "M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" },
    ],
  },
  {
    section: "Insights",
    items: [
      { to: "/benchmarks", label: "Perf Metrics", icon: "M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" },
      { to: "/siem", label: "SIEM Stats", icon: "M16 8v8m-4-5v5m-4-2v2m-2 4h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" },
      { to: "/reports", label: "Reports", icon: "M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" },
      { to: "/configs", label: "Configs", icon: "M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z M15 12a3 3 0 11-6 0 3 3 0 016 0z" },
    ],
  },
  {
    section: "Settings",
    items: [
      { to: "/account", label: "Account", icon: "M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z" },
      { to: "/teams", label: "Teams", minRole: "admin", icon: "M18 18.72a9.094 9.094 0 003.741-.479 3 3 0 00-4.682-2.72m.94 3.198l.001.031c0 .225-.012.447-.037.666A11.944 11.944 0 0112 21c-2.17 0-4.207-.576-5.963-1.584A6.062 6.062 0 016 18.719m12 0a5.971 5.971 0 00-.941-3.197m0 0A5.995 5.995 0 0012 12.75a5.995 5.995 0 00-5.058 2.772m0 0a3 3 0 00-4.681 2.72 8.986 8.986 0 003.74.477m.94-3.197a5.971 5.971 0 00-.94 3.197M15 6.75a3 3 0 11-6 0 3 3 0 016 0zm6 3a2.25 2.25 0 11-4.5 0 2.25 2.25 0 014.5 0zm-13.5 0a2.25 2.25 0 11-4.5 0 2.25 2.25 0 014.5 0z" },
      { to: "/notifications", label: "Notifications", minRole: "admin", icon: "M14.857 17.082a23.848 23.848 0 005.454-1.31A8.967 8.967 0 0118 9.75v-.7V9A6 6 0 006 9v.75a8.967 8.967 0 01-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 01-5.714 0m5.714 0a3 3 0 11-5.714 0" },
    ],
  },
];

const ROLE_RANK = { viewer: 0, operator: 1, admin: 2 };
const canAccess = (user, minRole) => !minRole || (ROLE_RANK[user.role] ?? -1) >= ROLE_RANK[minRole];

function Icon({ d }) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" d={d} />
    </svg>
  );
}

const SIEM_TYPES = ["Wazuh", "OSSEC", "OSSIM", "UTMstack", "Elastic"];

const CAPABILITIES = [
  { title: "Fleet", body: "Deploy, group, and bulk-manage containerized SIEM agents from one console." },
  { title: "Testing", body: "Replay attacks and log traffic against live agents to see how each SIEM reacts." },
  { title: "Insights", body: "Benchmark ingestion latency and compare detection performance across platforms." },
];

function AboutModal({ onClose }) {
  return (
    <Modal title="About Habeny" onClose={onClose}>
      <p className="about-lead">
        Habeny spins up disposable SIEM agents in containers so you can throw real attack and log
        traffic at them and measure what happens — before any of it touches production.
      </p>

      <div className="section-title">Supported SIEM platforms</div>
      <div className="about-tags">
        {SIEM_TYPES.map((s) => <span key={s} className="tag">{s}</span>)}
      </div>

      <div className="section-title">What you can do here</div>
      <div className="about-features">
        {CAPABILITIES.map((c) => (
          <div className="about-feature" key={c.title}>
            <h4>{c.title}</h4>
            <p>{c.body}</p>
          </div>
        ))}
      </div>

      <div className="about-meta">
        <span><strong>Version</strong> {__APP_VERSION__}</span>
        <span><strong>Runtime</strong> LXC containers</span>
        <span><strong>Telemetry</strong> Live over WebSocket</span>
      </div>
    </Modal>
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

const TITLES = { "/": "Dashboard", "/system": "System Info", "/managers": "Managers", "/agents": "Containers", "/deploy": "Deploy", "/groups": "Groups", "/bulk": "Bulk Operations", "/logs": "Log Upload", "/syslog-config": "Syslog Config", "/simulations": "Simulations", "/benchmark-runner": "Benchmark Runner", "/benchmarks": "Perf Metrics", "/siem": "SIEM Stats", "/reports": "Reports", "/configs": "Configs", "/activity": "Activity Log", "/account": "Account", "/monitoring": "Monitoring", "/notifications": "Notifications", "/teams": "Teams" };

// Active alerts in the header, checked every minute
function AlertBadge() {
  const [alerts, setAlerts] = useState([]);
  useEffect(() => {
    let stopped = false;
    const load = () => api.getAlerts().then((res) => { if (!stopped) setAlerts(res.data.alerts); }).catch(() => {});
    load();
    const timer = setInterval(load, 60000);
    return () => { stopped = true; clearInterval(timer); };
  }, []);
  if (!alerts.length) return null;
  const critical = alerts.some((a) => a.severity === "critical");
  return (
    <NavLink to="/monitoring" className={`header-alerts${critical ? "" : " warning"}`}>
      {alerts.length} alert{alerts.length === 1 ? "" : "s"}
    </NavLink>
  );
}

export default function App() {
  const { status, user, error, refresh } = useAuth();

  if (status === "loading") {
    return <div className="auth-page"><Spinner /></div>;
  }
  if (status === "error") {
    return (
      <div className="auth-page">
        <div className="auth-card">
          <h1 className="auth-title">Can't reach the server</h1>
          <p className="auth-subtitle">{error}</p>
          <button className="btn btn-primary auth-submit" onClick={refresh}>Retry</button>
        </div>
      </div>
    );
  }
  if (!user) return <Login />;
  return (
    <MetricsProvider>
      <AppShell user={user} />
    </MetricsProvider>
  );
}

function AppShell({ user }) {
  const { logout } = useAuth();
  const { connected } = useMetricsSocket();
  const location = useLocation();
  const title = TITLES[location.pathname] || "Habeny";
  const [aboutOpen, setAboutOpen] = useState(false);

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <div className="brand-wordmark">
            habeny<span className="brand-cursor" aria-hidden="true" />
          </div>
          <p>Multi-SIEM Container Platform</p>
        </div>
        <nav className="sidebar-nav">
          {NAV.map((group) => ({ ...group, items: group.items.filter((n) => canAccess(user, n.minRole)) }))
            .filter((group) => group.items.length)
            .map((group) => (
            <div key={group.section}>
              <div className="nav-section">{group.section}</div>
              {group.items.map((n) => (
                <NavLink key={n.to} to={n.to} end={n.to === "/"} className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
                  <Icon d={n.icon} />
                  {n.label}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        <button type="button" className="sidebar-footer" onClick={() => setAboutOpen(true)}>
          <span>About Habeny</span>
          <span>v{__APP_VERSION__}</span>
        </button>
      </aside>

      <div className="main-area">
        <header className="header">
          <span className="header-title">{title}</span>
          <div className="header-actions">
            <div className="ws-badge">
              <span className={`ws-dot${connected ? " on" : ""}`} />
              {connected ? "Live" : "Disconnected"}
            </div>
            <AlertBadge />
            {user.role === "viewer" && <span className="header-readonly" title="Viewer role: read-only access">Read-only</span>}
            <NavLink to="/account" className="header-user" title="Account settings">{user.username}</NavLink>
            <button type="button" className="btn btn-secondary btn-sm" onClick={logout}>Sign out</button>
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
            <Route path="/account" element={<Account />} />
            <Route path="/monitoring" element={<Monitoring />} />
            {user.is_admin && <Route path="/notifications" element={<Notifications />} />}
            {user.is_admin && <Route path="/teams" element={<Teams />} />}
          </Routes>
        </div>
      </div>

      {aboutOpen && <AboutModal onClose={() => setAboutOpen(false)} />}

      <Toasts />
    </div>
  );
}
