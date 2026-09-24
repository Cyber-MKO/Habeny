"""
Housekeeping in the background of the web app, so data doesn't grow without bound:

- every 10 s: save buffered API latency samples and job progress (app/services/records.py)
- every hour: delete data past its retention (see the HABENY_*_RETENTION_DAYS settings)
  and take a scheduled backup when one is due (app/services/backup.py)

`habeny prune` runs the pruning by hand.
"""
import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import config
from app.config import DB_PATH, LOGS_DIR, REPORTS_DIR

logger = logging.getLogger(__name__)

FLUSH_EVERY = 10
PRUNE_EVERY = 3600
HIGH_FREQUENCY_METRICS = ["system", "api_latency"]


def _cutoff(days: int) -> datetime | None:
    return datetime.now(timezone.utc) - timedelta(days=days) if days > 0 else None


def _old_files(directory: Path, pattern: str, cutoff: datetime, date_of: Callable[[Path], datetime | None]):
    for path in directory.glob(pattern):
        when = date_of(path)
        if when is not None and when < cutoff:
            yield path


def _activity_file_date(path: Path) -> datetime | None:
    try:  # activity_YYYYMMDD.json; the whole day must be past the cutoff
        return datetime.strptime(path.stem.split("_", 1)[1], "%Y%m%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
    except (IndexError, ValueError):
        return None


def _mtime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)


def prune(dry_run: bool = False) -> dict:
    """Delete data past its retention. Returns what was (or, dry run, would be) removed."""
    from app.db import delete_expired_api_tokens, prune_expired_sessions, prune_metrics

    removed = {"metric_samples": 0, "history_metrics": 0, "activity_files": 0, "report_files": 0,
               "expired_sessions": 0, "expired_tokens": 0, "finished_jobs": 0}

    samples_cutoff = _cutoff(config.get("HABENY_METRICS_RETENTION_DAYS"))
    history_cutoff = _cutoff(config.get("HABENY_HISTORY_RETENTION_DAYS"))
    reports_cutoff = _cutoff(config.get("HABENY_REPORT_RETENTION_DAYS"))

    old_activity = list(_old_files(LOGS_DIR, "activity_*.json", history_cutoff, _activity_file_date)) \
        if history_cutoff else []
    old_reports = [p for p in REPORTS_DIR.glob("*") if p.is_file() and _mtime(p) < reports_cutoff] \
        if reports_cutoff else []
    if dry_run:
        removed.update(activity_files=len(old_activity), report_files=len(old_reports))
        return removed

    if samples_cutoff:
        removed["metric_samples"] = prune_metrics(DB_PATH, samples_cutoff.isoformat(), HIGH_FREQUENCY_METRICS)
    if history_cutoff:
        removed["history_metrics"] = prune_metrics(DB_PATH, history_cutoff.isoformat(),
                                                   exclude_types=HIGH_FREQUENCY_METRICS)
        from app.state import STORES
        removed["finished_jobs"] = sum(store.prune(history_cutoff.isoformat()) for store in STORES)
    for path in old_activity:
        path.unlink(missing_ok=True)
    removed["activity_files"] = len(old_activity)
    for path in old_reports:
        path.unlink(missing_ok=True)
    removed["report_files"] = len(old_reports)
    removed["expired_sessions"] = prune_expired_sessions(DB_PATH)
    removed["expired_tokens"] = delete_expired_api_tokens(DB_PATH)
    if any(removed.values()):
        logger.info("Pruned old data: " + ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in removed.items() if v),
                    extra={"fields": {"pruned": removed}})
    return removed


class Maintenance:
    """The background thread. Each task is isolated: one failing doesn't stop the others."""

    def __init__(self):
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._next_prune = time.monotonic() + 60  # shortly after start, then hourly

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="habeny-maintenance", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=15)
        self._flush()  # don't lose the last samples

    def _flush(self) -> None:
        from app.middleware import flush_latency_samples
        from app.state import flush_persisted_state
        for name, task in (("saving API latency samples", flush_latency_samples),
                           ("saving job progress", flush_persisted_state)):
            try:
                task()
            except Exception:
                logger.exception(f"Maintenance: {name} failed")

    def _run(self) -> None:
        while not self._stop.wait(FLUSH_EVERY):
            self._flush()
            if time.monotonic() >= self._next_prune:
                self._next_prune = time.monotonic() + PRUNE_EVERY
                for name, task in (("pruning", prune), ("scheduled backup", _backup_if_due)):
                    try:
                        task()
                    except Exception:
                        logger.exception(f"Maintenance: {name} failed")


def _backup_if_due() -> None:
    from app.services.backup import backup_if_due
    backup_if_due()


maintenance = Maintenance()
