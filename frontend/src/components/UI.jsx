import { useEffect, useId, useRef, useState } from "react";


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
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {children && <div className="btn-group">{children}</div>}
    </div>
  );
}

// A container that scrolls sideways on narrow screens; while it does, it's focusable so
// keyboard users can scroll it too
export function ScrollArea({ className = "table-wrap", label, children }) {
  const ref = useRef(null);
  const [scrolls, setScrolls] = useState(false);
  useEffect(() => {
    const check = () => setScrolls(Boolean(ref.current && ref.current.scrollWidth > ref.current.clientWidth + 1));
    check();
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, [children]);
  return (
    <div ref={ref} className={className} {...(scrolls ? { tabIndex: 0, role: "region", "aria-label": label || "Table" } : {})}>
      {children}
    </div>
  );
}

export function DataTable({ columns, rows, onRowClick, emptyMsg = "No data", label }) {
  if (!rows || !rows.length) return <Empty message={emptyMsg} />;
  return (
    <ScrollArea label={label}>
      <table>
        <thead>
          <tr>{columns.map((c) => <th key={c.key} scope="col">{c.label || <span className="sr-only">{c.key === "actions" ? "Actions" : c.key}</span>}</th>)}</tr>
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
    </ScrollArea>
  );
}

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

// Keeps keyboard focus inside a dialog: focus moves in on open, Tab cycles, Escape closes,
// and focus returns to whatever opened it
export function useFocusTrap(ref, onEscape) {
  const escape = useRef(onEscape);
  useEffect(() => { escape.current = onEscape; });
  useEffect(() => {
    const node = ref.current;
    if (!node) return undefined;
    const previous = document.activeElement;
    const items = () => [...node.querySelectorAll(FOCUSABLE)].filter((el) => !el.closest("[hidden]"));
    const first = node.querySelector("[data-autofocus]") || node.querySelector("input, select, textarea") || items()[0] || node;
    first.focus();
    const onKey = (e) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        escape.current?.();
      } else if (e.key === "Tab") {
        const list = items();
        if (!list.length) return e.preventDefault();
        const [head, tail] = [list[0], list[list.length - 1]];
        if (e.shiftKey && (document.activeElement === head || document.activeElement === node)) {
          e.preventDefault();
          tail.focus();
        } else if (!e.shiftKey && document.activeElement === tail) {
          e.preventDefault();
          head.focus();
        }
      }
    };
    node.addEventListener("keydown", onKey);
    return () => {
      node.removeEventListener("keydown", onKey);
      if (previous && typeof previous.focus === "function") previous.focus();
    };
  }, [ref]);
}

export function Modal({ title, onClose, children, footer, wide }) {
  const ref = useRef(null);
  const titleId = useId();
  useFocusTrap(ref, onClose);
  return (
    <div className="modal-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className={`modal-content${wide ? " modal-wide" : ""}`} role="dialog" aria-modal="true" aria-labelledby={titleId} ref={ref} tabIndex={-1}>
        <div className="modal-header">
          <h2 className="modal-title" id={titleId}>{title}</h2>
          <button type="button" className="modal-close" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-footer">{footer}</div>}
      </div>
    </div>
  );
}
