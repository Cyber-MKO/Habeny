"""
Activity logging — in-memory list plus daily JSONL files under LOGS_DIR.
"""
import json
import logging
from typing import Any, Dict, List, Optional

from app.config import LOGS_DIR
from app.models import utc_now
from app.state import activity_logs

logger = logging.getLogger(__name__)


def log_activity(action: str, details: Dict[str, Any], status: str = "success"):
    """Log activity to in-memory store and file"""
    activity = {
        "timestamp": utc_now().isoformat(),
        "action": action,
        "status": status,
        "details": details
    }
    activity_logs.append(activity)

    # Also log to file
    log_file = LOGS_DIR / f"activity_{utc_now().strftime('%Y%m%d')}.json"
    with open(log_file, 'a') as f:
        f.write(json.dumps(activity) + "\n")

    logger.info(f"Activity logged: {action} - {status}")


def read_activity_logs_from_files(action: Optional[str] = None) -> List[Dict[str, Any]]:
    """Read activity logs from JSONL files."""
    logs = []
    for log_file in sorted(LOGS_DIR.glob("activity_*.json"), reverse=True):
        try:
            with open(log_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if action and entry.get("action") != action:
                        continue
                    logs.append(entry)
        except Exception:
            continue
    logs.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
    return logs
