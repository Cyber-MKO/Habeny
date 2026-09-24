"""
Data retention: old samples, history, activity files, reports and sessions are pruned;
live metrics are collected once per interval however many dashboards are open.
"""
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import pytest

from app.config import DB_PATH, LOGS_DIR, REPORTS_DIR
from app.services import maintenance


def _ago(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


@pytest.fixture()
def db(app):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM metrics")
    conn.commit()
    yield conn
    conn.close()


def _metric(conn, metric_type, days_ago, name="m"):
    conn.execute("INSERT INTO metrics (metric_type, metric_name, value, tags, recorded_at) VALUES (?, ?, 1, NULL, ?)",
                 (metric_type, name, _ago(days_ago)))
    conn.commit()


def _count(conn, metric_type):
    return conn.execute("SELECT COUNT(*) FROM metrics WHERE metric_type = ?", (metric_type,)).fetchone()[0]


def test_samples_and_history_have_separate_retention(db, monkeypatch):
    monkeypatch.setenv("HABENY_METRICS_RETENTION_DAYS", "30")
    monkeypatch.setenv("HABENY_HISTORY_RETENTION_DAYS", "365")
    for t in ("system", "api_latency", "deployment"):
        _metric(db, t, 1)
        _metric(db, t, 40)
        _metric(db, t, 400)
    removed = maintenance.prune()
    assert _count(db, "system") == 1 and _count(db, "api_latency") == 1  # 40 and 400 days old gone
    assert _count(db, "deployment") == 2  # only the 400-day-old deployment result gone
    assert removed["metric_samples"] == 4 and removed["history_metrics"] == 1


def test_zero_means_keep_forever(db, monkeypatch):
    monkeypatch.setenv("HABENY_METRICS_RETENTION_DAYS", "0")
    monkeypatch.setenv("HABENY_HISTORY_RETENTION_DAYS", "0")
    _metric(db, "system", 4000)
    _metric(db, "deployment", 4000)
    maintenance.prune()
    assert _count(db, "system") == 1 and _count(db, "deployment") == 1


def test_large_prunes_run_in_batches(db, monkeypatch):
    monkeypatch.setenv("HABENY_METRICS_RETENTION_DAYS", "1")
    old = _ago(5)
    db.executemany("INSERT INTO metrics (metric_type, metric_name, value, tags, recorded_at) VALUES "
                   "('system', 'x', 1, NULL, ?)", [(old,)] * 12_345)
    db.commit()
    from app.db import prune_metrics
    assert prune_metrics(DB_PATH, _ago(1), ["system"], batch=1000) == 12_345
    assert _count(db, "system") == 0


def test_old_activity_files_are_deleted(app, monkeypatch):
    monkeypatch.setenv("HABENY_HISTORY_RETENTION_DAYS", "30")
    old = LOGS_DIR / f"activity_{(datetime.now(timezone.utc) - timedelta(days=45)):%Y%m%d}.json"
    recent = LOGS_DIR / f"activity_{(datetime.now(timezone.utc) - timedelta(days=29)):%Y%m%d}.json"
    other = LOGS_DIR / "not-an-activity-file.json"
    for path in (old, recent, other):
        path.write_text("{}\n")
    assert maintenance.prune(dry_run=True)["activity_files"] >= 1
    assert old.exists()  # dry run changes nothing
    maintenance.prune()
    assert not old.exists() and recent.exists() and other.exists()
    recent.unlink()
    other.unlink()


def test_report_files_kept_unless_retention_set(app, monkeypatch):
    report = REPORTS_DIR / "old-report.pdf"
    report.write_bytes(b"%PDF")
    two_weeks_ago = time.time() - 14 * 86400
    os.utime(report, (two_weeks_ago, two_weeks_ago))
    monkeypatch.setenv("HABENY_REPORT_RETENTION_DAYS", "0")
    maintenance.prune()
    assert report.exists()
    monkeypatch.setenv("HABENY_REPORT_RETENTION_DAYS", "7")
    maintenance.prune()
    assert not report.exists()


def test_expired_sessions_are_removed(admin_created):
    conn = sqlite3.connect(DB_PATH)
    user_id = conn.execute("SELECT id FROM users LIMIT 1").fetchone()[0]
    conn.execute("INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES ('expired-x', ?, ?, ?)",
                 (user_id, _ago(10), _ago(3)))
    conn.commit()
    assert maintenance.prune()["expired_sessions"] >= 1
    assert conn.execute("SELECT COUNT(*) FROM sessions WHERE token_hash='expired-x'").fetchone()[0] == 0


def test_dashboards_share_one_collection(db, monkeypatch):
    from app.routes import metrics

    calls = []
    real = metrics._collect_metrics_payload
    monkeypatch.setattr(metrics, "_collect_metrics_payload", lambda: calls.append(1) or real())
    monkeypatch.setattr(metrics, "_shared", {"at": float("-inf"), "payload": None})
    monkeypatch.setattr(metrics, "_last_saved", float("-inf"))
    for _ in range(10):  # ten viewers asking within one interval
        metrics.shared_metrics_payload()
    assert len(calls) == 1
    assert _count(db, "system") == 4  # one snapshot (4 values), not ten


def test_snapshots_are_saved_at_most_once_per_sample_interval(db, monkeypatch):
    from app.routes import metrics

    monkeypatch.setattr(metrics, "_last_saved", float("-inf"))
    monkeypatch.setattr(metrics, "LIVE_INTERVAL", 0)  # recompute every call
    for _ in range(5):
        metrics.shared_metrics_payload()
    assert _count(db, "system") == 4  # METRICS_SAMPLE_SECONDS (60) hasn't passed
