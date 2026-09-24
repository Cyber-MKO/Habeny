"""
Durable in-process state: dicts of JSON records (simulations, reports, deployments, log
schedules, config templates) persisted in the `records` table, so a restart doesn't lose
them.

PersistentStore is a dict, so existing code keeps using it as one. New and replaced
records are saved immediately; records changed in place (progress counters, status
updates from background tasks) are saved by flush(), which the maintenance task runs
every 10 seconds and at shutdown. When Habeny starts, records that were running are
marked "interrupted": nothing disappears silently. Log schedules then resume by
themselves (app/services/logs.py).
"""
import hashlib
import json
import logging
import sqlite3
import threading
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

INTERRUPTED = "interrupted"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PersistentStore(dict):
    def __init__(self, kind: str, active_statuses: Iterable[str] = ("running", "starting", "queued"),
                 transient_keys: Iterable[str] = ("task",), prunable: bool = True):
        super().__init__()
        self.kind = kind
        self.active_statuses = set(active_statuses)
        self.transient_keys = set(transient_keys)
        self.prunable = prunable  # finished records expire with HABENY_HISTORY_RETENTION_DAYS
        self._db: Path | None = None
        self._saved: dict[str, str] = {}  # id -> hash of what's in the database
        self._lock = threading.RLock()

    # ── persistence ──

    def _serialize(self, value: Any) -> str:
        if isinstance(value, dict):
            value = {k: v for k, v in value.items() if k not in self.transient_keys}
        return json.dumps(value, default=str, sort_keys=True)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db, timeout=30)

    def load(self, db_path: Path) -> list[str]:
        """Attach to the database and load everything. Returns the ids of records that were
        running when Habeny stopped (now marked interrupted)."""
        self._db = db_path
        interrupted = []
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute("SELECT id, data FROM records WHERE kind = ? ORDER BY created_at",
                                    (self.kind,)).fetchall()
            finally:
                conn.close()
            for record_id, data in rows:
                value = json.loads(data)
                super().__setitem__(record_id, value)
                self._saved[record_id] = hashlib.sha1(data.encode()).hexdigest()
                if isinstance(value, dict) and value.get("status") in self.active_statuses:
                    value["status_before_restart"] = value["status"]
                    value["status"] = INTERRUPTED
                    value["interrupted_at"] = _now()
                    interrupted.append(record_id)
            for record_id in interrupted:
                self.save(record_id)
        if interrupted:
            logger.warning(f"{len(interrupted)} {self.kind} record(s) were in progress when Habeny stopped; "
                           f"marked '{INTERRUPTED}'")
        return interrupted

    def save(self, key: str) -> None:
        if self._db is None:
            return
        with self._lock:
            value = super().get(key)
            if value is None:
                return
            try:
                data = self._serialize(value)
            except (RuntimeError, TypeError, ValueError) as e:  # mutated mid-serialization; next flush
                logger.debug(f"Deferred saving {self.kind} {key}: {e}")
                return
            digest = hashlib.sha1(data.encode()).hexdigest()
            if self._saved.get(key) == digest:
                return
            status = value.get("status") if isinstance(value, dict) else None
            now = _now()
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT INTO records (kind, id, status, data, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT(kind, id) DO UPDATE SET status = excluded.status, data = excluded.data,"
                    " updated_at = excluded.updated_at",
                    (self.kind, key, status, data, now, now),
                )
                conn.commit()
            finally:
                conn.close()
            self._saved[key] = digest

    def flush(self) -> int:
        """Save records changed in place since they were last saved."""
        saved = 0
        for key in list(self.keys()):
            before = self._saved.get(key)
            self.save(key)
            saved += self._saved.get(key) != before
        return saved

    def _delete(self, key: str) -> None:
        self._saved.pop(key, None)
        if self._db is None:
            return
        conn = self._connect()
        try:
            conn.execute("DELETE FROM records WHERE kind = ? AND id = ?", (self.kind, key))
            conn.commit()
        finally:
            conn.close()

    def prune(self, before: str) -> int:
        """Forget finished records last updated before `before` (ISO time)."""
        if not self.prunable or self._db is None:
            return 0
        with self._lock:
            conn = self._connect()
            try:
                placeholders = ",".join("?" * len(self.active_statuses))
                ids = [r[0] for r in conn.execute(
                    f"SELECT id FROM records WHERE kind = ? AND updated_at < ? AND COALESCE(status, '') "
                    f"NOT IN ({placeholders})", (self.kind, before, *self.active_statuses))]
            finally:
                conn.close()
            for key in ids:
                super().pop(key, None)
                self._delete(key)
            return len(ids)

    # ── dict interface ──

    def __setitem__(self, key, value) -> None:
        with self._lock:
            super().__setitem__(key, value)
            self.save(key)

    def __delitem__(self, key) -> None:
        with self._lock:
            super().__delitem__(key)
            self._delete(key)

    _MISSING = object()

    def pop(self, key, default=_MISSING):
        with self._lock:
            if key not in self:
                if default is PersistentStore._MISSING:
                    raise KeyError(key)
                return default
            value = super().pop(key)
            self._delete(key)
            return value

    def setdefault(self, key, default=None):
        with self._lock:
            if key not in self:
                self[key] = default
            return super().__getitem__(key)

    def update(self, *args, **kwargs) -> None:
        for key, value in dict(*args, **kwargs).items():
            self[key] = value

    def clear(self) -> None:
        for key in list(self.keys()):
            del self[key]
