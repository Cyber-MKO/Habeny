import { Fragment, useEffect, useState, useCallback } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { useStore } from "../store";
import { Details, humanize } from "../components/Details";
import { PageHeader, Pill, Spinner, Empty } from "../components/UI";

const PAGE_SIZES = [25, 50, 100, 250];
const EMPTY_FILTERS = { q: "", action: "", user: "", status: "", since: "", until: "" };

function summary(details) {
  const entries = Object.entries(details || {}).filter(([, v]) => v !== null && typeof v !== "object");
  return entries.slice(0, 3).map(([k, v]) => `${humanize(k)}: ${v}`).join(" · ");
}

// Only set filters go to the API (and into export links)
function activeFilters(filters) {
  return Object.fromEntries(Object.entries(filters).filter(([, v]) => v));
}

export default function Activity() {
  const { user } = useAuth();
  const { toast } = useStore();
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [applied, setApplied] = useState(EMPTY_FILTERS);
  const [facets, setFacets] = useState({ actions: [], users: [] });
  const [page, setPage] = useState({ logs: [], total: 0 });
  const [loading, setLoading] = useState(true);
  const [limit, setLimit] = useState(50);
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState(null);
  const [verification, setVerification] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.getActivity({ limit, offset, ...activeFilters(applied) });
      setPage({ logs: res.data?.logs || [], total: res.data?.total || 0 });
    } catch (e) { toast(e.message, "error"); }
    finally { setLoading(false); }
  }, [limit, offset, applied, toast]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    api.getActivityFacets().then((res) => setFacets(res.data)).catch(() => {});
  }, []);

  const set = (key) => (e) => setFilters((f) => ({ ...f, [key]: e.target.value }));
  const apply = (e) => { e?.preventDefault(); setOffset(0); setApplied(filters); };
  const reset = () => { setFilters(EMPTY_FILTERS); setApplied(EMPTY_FILTERS); setOffset(0); };

  const verify = async () => {
    try {
      const res = await api.verifyActivity();
      setVerification(res);
    } catch (e) { toast(e.message, "error"); }
  };

  const { logs, total } = page;
  const exportParams = activeFilters(applied);
  return (
    <>
      <PageHeader title="Activity Log" subtitle={`${total.toLocaleString()} ${Object.keys(exportParams).length ? "matching " : ""}entries`}>
        <a className="btn btn-secondary" href={api.activityExportUrl({ ...exportParams, format: "csv" })} download>Export CSV</a>
        <a className="btn btn-secondary" href={api.activityExportUrl({ ...exportParams, format: "jsonl" })} download>Export JSON Lines</a>
        {user.is_admin && <button className="btn btn-secondary" onClick={verify}>Verify integrity</button>}
      </PageHeader>

      {verification && (
        <div className={verification.data.ok ? "auth-notice" : "auth-error"} role="status">
          {verification.message}
          {verification.data.ok && verification.data.head_hash && <> · latest hash <code>{verification.data.head_hash.slice(0, 16)}…</code></>}
        </div>
      )}

      <form className="filters" onSubmit={apply} role="search" aria-label="Filter the activity log">
        <div className="field">
          <label htmlFor="act-q">Search</label>
          <input id="act-q" className="input" type="search" placeholder="Container, group, username…" value={filters.q} onChange={set("q")} />
        </div>
        <div className="field">
          <label htmlFor="act-action">Action</label>
          <select id="act-action" className="select" value={filters.action} onChange={set("action")}>
            <option value="">Any</option>
            {facets.actions.map((a) => <option key={a} value={a}>{humanize(a)}</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor="act-user">User</label>
          <select id="act-user" className="select" value={filters.user} onChange={set("user")}>
            <option value="">Anyone</option>
            {facets.users.map((u) => <option key={u} value={u}>{u}</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor="act-status">Result</label>
          <select id="act-status" className="select" value={filters.status} onChange={set("status")}>
            <option value="">Any</option>
            <option value="success">Success</option>
            <option value="partial">Partial</option>
            <option value="error">Error</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="act-since">From</label>
          <input id="act-since" className="input" type="date" value={filters.since} onChange={set("since")} />
        </div>
        <div className="field">
          <label htmlFor="act-until">To</label>
          <input id="act-until" className="input" type="date" value={filters.until} onChange={set("until")} />
        </div>
        <div className="field filters-actions">
          <button type="submit" className="btn btn-primary">Apply</button>
          <button type="button" className="btn btn-secondary" onClick={reset}>Reset</button>
        </div>
      </form>

      <div className="card">
        {loading ? <Spinner /> : !logs.length ? <Empty message="No matching activity" /> : (
          <div className="table-wrap">
            <table>
              <caption className="sr-only">Activity log entries, newest first</caption>
              <thead>
                <tr>
                  <th scope="col">Time</th><th scope="col">User</th><th scope="col">Action</th>
                  <th scope="col">Result</th><th scope="col">Summary</th>
                </tr>
              </thead>
              <tbody>
                {logs.map((r) => (
                  <Fragment key={r.id}>
                    <tr>
                      <td>
                        <button type="button" className="link-btn" aria-expanded={open === r.id} aria-controls={`act-${r.id}`}
                          onClick={() => setOpen(open === r.id ? null : r.id)}>
                          {new Date(r.timestamp).toLocaleString()}
                        </button>
                      </td>
                      <td>{r.user || <span className="muted">system</span>}{r.token && <span className="tag" title="Done with an API token">token {r.token}</span>}</td>
                      <td>{humanize(r.action)}</td>
                      <td><Pill status={r.status} /></td>
                      <td className="activity-summary">{summary(r.details) || "—"}</td>
                    </tr>
                    {open === r.id && (
                      <tr className="activity-detail" id={`act-${r.id}`}>
                        <td colSpan={5}>
                          <Details data={{ ...r.details, entry: r.id, request_id: r.request_id, from_ip: r.ip }} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <nav className="pager" aria-label="Activity pages">
        <label htmlFor="act-size" className="muted">Per page</label>
        <select id="act-size" className="select select-sm" value={limit} onChange={(e) => { setLimit(Number(e.target.value)); setOffset(0); }}>
          {PAGE_SIZES.map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
        <button className="btn btn-secondary btn-sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))}>Previous</button>
        <span className="muted">{total ? `${offset + 1}–${Math.min(offset + limit, total)} of ${total.toLocaleString()}` : "0"}</span>
        <button className="btn btn-secondary btn-sm" disabled={offset + limit >= total} onClick={() => setOffset(offset + limit)}>Next</button>
      </nav>
    </>
  );
}
