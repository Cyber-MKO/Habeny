"""
Activity logging — in-memory list plus daily JSONL files under LOGS_DIR.
"""
import json
import logging
from typing import Any

from app.config import LOGS_DIR
from app.logging_config import request_context
from app.models import utc_now

logger = logging.getLogger(__name__)


def log_activity(action: str, details: dict[str, Any], status: str = "success"):
    """Log activity to in-memory store and file"""
    activity = {
        "timestamp": utc_now().isoformat(),
        "action": action,
        "status": status,
        "details": details
    }
    ctx = request_context.get()
    if ctx:  # which request (and who) did it: search the server log for the request ID
        activity["request_id"] = ctx["id"]
        if ctx.get("user"):
            activity["user"] = ctx["user"]
    # Also log to file
    log_file = LOGS_DIR / f"activity_{utc_now().strftime('%Y%m%d')}.json"
    with open(log_file, 'a') as f:
        f.write(json.dumps(activity) + "\n")

    logger.info(f"Activity logged: {action} - {status}")


def read_activity_page(action: str | None, offset: int, limit: int) -> tuple[list[dict[str, Any]], int]:
    """Newest-first page of activity entries plus the total number of matching entries.

    Entries are only ever appended, with the current time, to the current day's file,
    so reading files newest-first and each file bottom-up yields newest-first order
    without loading and sorting everything. Only the entries on the requested page
    are fully parsed; without an action filter the rest are just counted.
    """
    page: list[dict[str, Any]] = []
    total = 0
    needle = f'"action": {json.dumps(action)}' if action else None
    for log_file in sorted(LOGS_DIR.glob("activity_*.json"), reverse=True):
        try:
            with open(log_file) as f:
                lines = f.read().splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            line = line.strip()
            if not (line.startswith("{") and line.endswith("}")):
                continue  # blank or partially written line
            if needle is not None:
                if needle not in line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("action") != action:
                    continue
            elif offset <= total < offset + limit:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
            else:
                total += 1
                continue
            if offset <= total < offset + limit:
                page.append(entry)
            total += 1
    return page, total
