"""
The audit trail: every recorded action, in the database, tamper-evident.

Each entry stores the SHA-256 of the previous entry's hash plus its own content, so
changing, removing or reordering any entry breaks the chain from there on
(`habeny audit verify`, GET /activity/verify). Updates are refused by a trigger.
Each new entry's hash also goes to the server log (logger `habeny.audit`), so a copy
shipped off the server (journald forwarding, JSON logs) can prove what the chain
looked like even if the whole database were rewritten.

Old entries are pruned after HABENY_HISTORY_RETENTION_DAYS; the last pruned entry's
id and hash are kept as the anchor the remaining chain is verified from.
"""
import contextlib
import csv
import hashlib
import io
import json
import logging
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.logging_config import request_context
from app.models import utc_now

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("habeny.audit")

GENESIS = "0" * 64
COLUMNS = ("id", "timestamp", "action", "status", "user", "token", "ip", "request_id", "details", "prev_hash", "hash")


def canonical_details(details: dict[str, Any] | None) -> str:
    return json.dumps(details or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def entry_hash(prev_hash: str, entry_id: int, ts: str, action: str, status: str, user: str | None,
               token: str | None, ip: str | None, request_id: str | None, details: str) -> str:
    """The chain link. Never change this: every stored hash depends on it."""
    payload = json.dumps([prev_hash, entry_id, ts, action, status, user, token, ip, request_id, details],
                         separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


def _anchor(conn) -> tuple[int, str]:
    rows = dict(conn.execute("SELECT key, value FROM meta WHERE key IN ('audit_anchor_id', 'audit_anchor_hash')"))
    return int(rows.get("audit_anchor_id", 0)), rows.get("audit_anchor_hash", GENESIS)


def append(conn: sqlite3.Connection, ts: str, action: str, status: str, user: str | None, token: str | None,
           ip: str | None, request_id: str | None, details: dict[str, Any] | str) -> tuple[int, str]:
    """Add one entry inside the caller's (immediate) transaction. Returns (id, hash)."""
    details_text = details if isinstance(details, str) else canonical_details(details)
    last = conn.execute("SELECT id, hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    if last:
        prev_id, prev_hash = last[0], last[1]
    else:
        prev_id, prev_hash = _anchor(conn)
    entry_id = prev_id + 1
    digest = entry_hash(prev_hash, entry_id, ts, action, status, user, token, ip, request_id, details_text)
    conn.execute(
        "INSERT INTO audit_log (id, ts, action, status, username, token, ip, request_id, details, prev_hash, hash)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (entry_id, ts, action, status, user, token, ip, request_id, details_text, prev_hash, digest),
    )
    return entry_id, digest


def record(action: str, details: dict[str, Any], status: str = "success", *, user: str | None = None) -> None:
    """Record an action, with who did it (from the request, or `user`), from where, and the request ID."""
    from app.config import DB_PATH

    ctx = request_context.get() or {}
    user = user or ctx.get("user")
    token, ip, request_id = ctx.get("token"), ctx.get("ip"), ctx.get("id")
    ts = utc_now().isoformat()
    try:
        conn = _connect(DB_PATH)
        try:
            conn.execute("BEGIN IMMEDIATE")  # one writer at a time keeps the chain linear
            entry_id, digest = append(conn, ts, action, status, user, token, ip, request_id, details)
            conn.execute("COMMIT")
        finally:
            conn.close()
    except sqlite3.Error as e:
        # Never lose the event: it still reaches the server log below
        logger.error(f"Couldn't write audit entry {action}: {e}")
        entry_id, digest = None, None
    audit_logger.info(
        f"{action} {status}" + (f" by {user}" if user else ""),
        extra={"fields": {"audit_id": entry_id, "audit_hash": digest, "action": action, "status": status,
                          "user": user, "token": token, "details": details}},
    )


# ── reading ─────────────────────────────────────────────────────────────

@dataclass
class Filters:
    action: str | None = None      # exact, or a prefix ending in "*" (e.g. "user_*")
    user: str | None = None
    status: str | None = None
    since: str | None = None       # ISO date or datetime, inclusive
    until: str | None = None       # ISO date (the whole day) or datetime, inclusive
    q: str | None = None           # text anywhere in the action or details

    def where(self) -> tuple[str, list]:
        clauses, args = [], []
        if self.action:
            if self.action.endswith("*"):
                clauses.append("action LIKE ? ESCAPE '\\'")
                args.append(_like_escape(self.action[:-1]) + "%")
            else:
                clauses.append("action = ?")
                args.append(self.action)
        if self.user:
            clauses.append("username = ? COLLATE NOCASE")
            args.append(self.user)
        if self.status:
            clauses.append("status = ?")
            args.append(self.status)
        if self.since:
            clauses.append("ts >= ?")
            args.append(self.since)
        if self.until:
            # A bare date means up to the end of that day
            clauses.append("ts < ?" if len(self.until) == 10 else "ts <= ?")
            args.append(_next_day(self.until) if len(self.until) == 10 else self.until)
        if self.q:
            clauses.append("(action LIKE ? ESCAPE '\\' OR details LIKE ? ESCAPE '\\')")
            args += [f"%{_like_escape(self.q)}%"] * 2
        return (" WHERE " + " AND ".join(clauses)) if clauses else "", args


def _like_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _next_day(date: str) -> str:
    from datetime import date as _date
    from datetime import timedelta
    return (_date.fromisoformat(date) + timedelta(days=1)).isoformat()


def _public(row: sqlite3.Row, with_hashes: bool = False) -> dict[str, Any]:
    entry = {
        "id": row["id"], "timestamp": row["ts"], "action": row["action"], "status": row["status"],
        "user": row["username"], "token": row["token"], "ip": row["ip"], "request_id": row["request_id"],
        "details": json.loads(row["details"]),
    }
    if with_hashes:
        entry.update(prev_hash=row["prev_hash"], hash=row["hash"])
    return {k: v for k, v in entry.items() if v is not None or k in ("details",)}


def query(filters: Filters, offset: int = 0, limit: int = 100) -> tuple[list[dict[str, Any]], int]:
    """Newest-first page of matching entries and how many match in total."""
    from app.config import DB_PATH

    where, args = filters.where()
    conn = _connect(DB_PATH)
    try:
        total = conn.execute(f"SELECT COUNT(*) FROM audit_log{where}", args).fetchone()[0]
        rows = conn.execute(f"SELECT * FROM audit_log{where} ORDER BY id DESC LIMIT ? OFFSET ?",
                            [*args, limit, offset]).fetchall()
    finally:
        conn.close()
    return [_public(r) for r in rows], total


def facets() -> dict[str, list[str]]:
    """The actions and users that appear, for filter menus."""
    from app.config import DB_PATH

    conn = _connect(DB_PATH)
    try:
        actions = [r[0] for r in conn.execute("SELECT DISTINCT action FROM audit_log ORDER BY action")]
        users = [r[0] for r in conn.execute(
            "SELECT DISTINCT username FROM audit_log WHERE username IS NOT NULL ORDER BY username COLLATE NOCASE")]
    finally:
        conn.close()
    return {"actions": actions, "users": users}


def export(filters: Filters, fmt: str) -> Iterator[str]:
    """Matching entries oldest first, as CSV or JSON Lines, with their hashes (so a copy can be
    checked against the chain later). Streams: memory use doesn't grow with the log."""
    from app.config import DB_PATH

    where, args = filters.where()
    conn = _connect(DB_PATH)
    try:
        cursor = conn.execute(f"SELECT * FROM audit_log{where} ORDER BY id", args)
        if fmt == "csv":
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(COLUMNS)
            yield buf.getvalue()
            for row in cursor:
                buf.seek(0)
                buf.truncate()
                writer.writerow([row["id"], row["ts"], row["action"], row["status"], row["username"] or "",
                                 row["token"] or "", row["ip"] or "", row["request_id"] or "", row["details"],
                                 row["prev_hash"], row["hash"]])
                yield buf.getvalue()
        else:
            for row in cursor:
                yield json.dumps(_public(row, with_hashes=True), ensure_ascii=False) + "\n"
    finally:
        conn.close()


# ── verification and pruning ────────────────────────────────────────────

def verify(db_path: Path | None = None) -> dict[str, Any]:
    """Recompute the chain. ok is False at the first entry that was changed, removed or reordered."""
    from app.config import DB_PATH

    conn = _connect(db_path or DB_PATH)
    try:
        expected_id, prev_hash = _anchor(conn)
        anchor_id = expected_id
        checked = 0
        problem = None
        for row in conn.execute("SELECT * FROM audit_log ORDER BY id"):
            expected_id += 1
            if row["id"] != expected_id:
                problem = {"id": expected_id, "reason": f"entry {expected_id} is missing (next is {row['id']})"}
                break
            if row["prev_hash"] != prev_hash:
                problem = {"id": row["id"], "reason": "the link to the previous entry doesn't match"}
                break
            digest = entry_hash(prev_hash, row["id"], row["ts"], row["action"], row["status"], row["username"],
                                row["token"], row["ip"], row["request_id"], row["details"])
            if digest != row["hash"]:
                problem = {"id": row["id"], "reason": "the entry was changed after it was written"}
                break
            prev_hash = digest
            checked += 1
    finally:
        conn.close()
    return {"ok": problem is None, "checked": checked, "anchor_id": anchor_id,
            "last_id": expected_id if problem is None else None, "head_hash": prev_hash if problem is None else None,
            "problem": problem}


def prune(before: str, dry_run: bool = False) -> int:
    """Delete entries older than `before`, keeping the last deleted one's id and hash as the anchor."""
    from app.config import DB_PATH

    conn = _connect(DB_PATH)
    try:
        conn.execute("BEGIN IMMEDIATE")
        last = conn.execute("SELECT id, hash FROM audit_log WHERE ts < ? ORDER BY id DESC LIMIT 1",
                            (before,)).fetchone()
        if not last:
            conn.execute("ROLLBACK")
            return 0
        count = conn.execute("SELECT COUNT(*) FROM audit_log WHERE id <= ?", (last["id"],)).fetchone()[0]
        if dry_run:
            conn.execute("ROLLBACK")
            return count
        conn.execute("DELETE FROM audit_log WHERE id <= ?", (last["id"],))
        conn.executemany("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                         [("audit_anchor_id", str(last["id"])), ("audit_anchor_hash", last["hash"])])
        conn.execute("COMMIT")
        return count
    except Exception:
        with contextlib.suppress(sqlite3.Error):
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
