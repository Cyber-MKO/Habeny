"""
Process-wide state shared between routes and services.

Only ever mutate these in place: other modules hold references to the same objects.
The stores are dicts persisted in the database (app/services/records.py), loaded at
startup by load_persisted_state(); a restart keeps them, with anything that was running
marked "interrupted".
"""
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.records import PersistentStore

# For /system/health uptime
PROCESS_STARTED_AT = time.monotonic()

simulations_db = PersistentStore("simulation")
reports_db = PersistentStore("report")
report_files = PersistentStore("report_files")
config_templates = PersistentStore("config_template", prunable=False)
scheduled_log_tasks = PersistentStore("log_schedule")

# Live deployment progress, keyed by deployment_id (see /agents/deploy/progress/{id})
deployment_progress: dict[str, dict[str, Any]] = PersistentStore("deployment")
deployment_progress_lock = threading.Lock()
MAX_TRACKED_DEPLOYMENTS = 20

STORES = [simulations_db, reports_db, report_files, config_templates, scheduled_log_tasks, deployment_progress]


def load_persisted_state(db_path: Path) -> dict[str, list[str]]:
    """Load every store; returns the ids that were interrupted, per kind."""
    return {store.kind: store.load(db_path) for store in STORES}


def import_legacy_config_templates(configs_dir: Path) -> int:
    """Templates used to be kept in memory (plus a JSON file each that was never read back),
    so they vanished on restart. Bring those files in once."""
    import json
    imported = 0
    for path in sorted(configs_dir.glob("*.json")):
        try:
            template = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        template_id = template.get("template_id") if isinstance(template, dict) else None
        if template_id and template_id not in config_templates:
            config_templates[template_id] = template
            imported += 1
    return imported


def interrupt_running_simulations() -> None:
    """A stop began: running simulations end and show as interrupted (their loops check the status)."""
    from app.services.records import INTERRUPTED
    for simulation in list(simulations_db.values()):
        if simulation.get("status") == "running":
            simulation["status_before_restart"] = "running"
            simulation["status"] = INTERRUPTED
            simulation["interrupted_at"] = datetime.now(timezone.utc).isoformat()


def flush_persisted_state() -> int:
    return sum(store.flush() for store in STORES)
