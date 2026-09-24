// Readable rendering of API data (objects, lists, dates, flags) instead of raw JSON

const ISO_DATE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/;

export function humanize(key) {
  const text = String(key).replace(/_/g, " ").replace(/\bid\b/gi, "ID").replace(/\bip\b/gi, "IP")
    .replace(/\bsiem\b/gi, "SIEM").replace(/\bcpu\b/gi, "CPU").replace(/\beps\b/gi, "EPS");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function isPlainObject(v) {
  return v !== null && typeof v === "object" && !Array.isArray(v);
}

export function Value({ value }) {
  if (value === null || value === undefined || value === "") return <span className="muted">—</span>;
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return Number.isInteger(value) ? value.toLocaleString() : value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  if (typeof value === "string") {
    if (ISO_DATE.test(value) && !Number.isNaN(Date.parse(value))) {
      return <time dateTime={value}>{new Date(value).toLocaleString()}</time>;
    }
    return value.length > 80 || value.includes("\n") ? <code className="details-long">{value}</code> : value;
  }
  if (Array.isArray(value)) {
    if (!value.length) return <span className="muted">none</span>;
    if (value.every((v) => !isPlainObject(v) && !Array.isArray(v))) return value.map(String).join(", ");
    if (value.every(isPlainObject)) return <RecordTable rows={value} />;
    return <ul className="plain-list">{value.map((v, i) => <li key={i}><Value value={v} /></li>)}</ul>;
  }
  if (isPlainObject(value)) return <Details data={value} nested />;
  return String(value);
}

// A list of similar objects as a small table (columns: the union of their keys)
export function RecordTable({ rows, limit = 50 }) {
  const keys = [...new Set(rows.flatMap((r) => Object.keys(r)))].slice(0, 8);
  return (
    <div className="table-wrap details-table">
      <table>
        <thead><tr>{keys.map((k) => <th key={k} scope="col">{humanize(k)}</th>)}</tr></thead>
        <tbody>
          {rows.slice(0, limit).map((r, i) => (
            <tr key={i}>{keys.map((k) => <td key={k}><Value value={r[k]} /></td>)}</tr>
          ))}
        </tbody>
      </table>
      {rows.length > limit && <p className="muted">…and {rows.length - limit} more</p>}
    </div>
  );
}

export function Details({ data, nested, hide = [] }) {
  if (!isPlainObject(data)) return <Value value={data} />;
  const entries = Object.entries(data).filter(([k]) => !hide.includes(k));
  if (!entries.length) return <span className="muted">No details</span>;
  return (
    <dl className={`details${nested ? " details-nested" : ""}`}>
      {entries.map(([k, v]) => (
        <div className="details-row" key={k}>
          <dt>{humanize(k)}</dt>
          <dd><Value value={v} /></dd>
        </div>
      ))}
    </dl>
  );
}
