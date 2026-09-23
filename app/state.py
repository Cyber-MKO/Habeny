"""
Process-wide in-memory state shared between routes and services.

Only ever mutate these in place — other modules hold references to the same objects.
"""
import threading
from typing import Any, Dict

simulations_db = {}
reports_db = {}
report_files = {}
activity_logs = []
config_templates = {}
scheduled_log_tasks = {}

# Live deployment progress, keyed by deployment_id (see /agents/deploy/progress/{id})
deployment_progress: Dict[str, Dict[str, Any]] = {}
deployment_progress_lock = threading.Lock()
MAX_TRACKED_DEPLOYMENTS = 20
