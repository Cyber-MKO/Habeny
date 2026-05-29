import React, { useState } from "react";

export function StatCard({ label, value, meta, color }) {
  return (
    <div className="card stat-card">
      <div className="stat-label">{label}</div>
      <div className={`stat-value${color ? ` ${color}` : ""}`}>{value}</div>
      {meta && <div className="stat-meta">{meta}</div>}
    </div>
  );
}

export function Pill({ status }) {
  const s = (status || "unknown").toLowerCase();
  return <span className={`pill pill-${s}`}>{s}</span>;
}

export function Spinner() {
  return <div className="spinner" />;
}

export function Empty({ message = "No data" }) {
  return <div className="empty"><p>{message}</p></div>;
}

export function PageHeader({ title, subtitle, children }) {
  return (
    <div className="page-header">
      <div>
        <h2>{title}</h2>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {children && <div className="btn-group">{children}</div>}
    </div>
  );
}

export function JsonBlock({ data }) {
  const text = typeof data === "string" ? data : JSON.stringify(data, null, 2);
  return <pre className="json-block">{text}</pre>;
}

export function DataTable({ columns, rows, onRowClick, emptyMsg = "No data" }) {
  if (!rows || !rows.length) return <Empty message={emptyMsg} />;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>{columns.map((c) => <th key={c.key}>{c.label}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={row.id || row.agent_id || row.agent_name || i} onClick={() => onRowClick?.(row)} style={onRowClick ? { cursor: "pointer" } : undefined}>
              {columns.map((c) => (
                <td key={c.key}>{c.render ? c.render(row) : row[c.key]}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Modal({ title, onClose, children }) {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <span className="modal-title">{title}</span>
          <button className="btn btn-sm btn-secondary" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  );
}
