"""
Log upload to containers — upload scripts, UTMstack filebeat wiring and recurring schedules.
"""
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.core.container import build_write_file_script
from app.core.lxc_backend import lxc
from app.core.shell import execute_in_container
from app.core.validation import validate_container_path
from app.models import LogUploadRequest, utc_now
from app.services.activity import log_activity
from app.services.agent_info import detect_siem_type, read_agent_metadata
from app.services.records import INTERRUPTED
from app.state import scheduled_log_tasks

logger = logging.getLogger(__name__)


def _build_log_upload_script(log_upload: LogUploadRequest) -> str:
    return build_write_file_script(log_upload.destination_path, log_upload.content, log_upload.append)


def escape_json_string(value: str) -> str:
    return (
        value
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def escape_bash_single_quotes(value: str) -> str:
    return value.replace("'", "'\"'\"'")


def _build_utmstack_filebeat_script(log_path: str) -> str:
    """Generate a script that adds a log path to UTMstack's filebeat config and restarts the collector.

    The default system.yml has ``#var.paths:`` (commented, no space).
    Three cases:
      1. Path already present → skip
      2. ``#var.paths:`` (default/commented) → uncomment and add path below
      3. ``var.paths:`` exists (already uncommented) → append path to list
    """
    validate_container_path(log_path)  # used inside grep/sed expressions below
    yml = "/opt/utmstack-linux-agent/beats/filebeat/modules.d/system.yml"
    return f"""
if [ ! -f {yml} ]; then exit 0; fi

if grep -qF '{log_path}' {yml} 2>/dev/null; then
  echo "Path {log_path} already in filebeat config"
  exit 0
fi

# Case: default commented "#var.paths:" — uncomment and add path.
# Matches the first occurrence only (syslog section, not auth section).
if grep -q '^ *#var\\.paths:' {yml} 2>/dev/null; then
  sed -i '0,/^ *#var\\.paths:/{{
    s|^ *#var\\.paths:.*|    var.paths:\\n      - {log_path}|
  }}' {yml}
# Case: already uncommented "var.paths:" — append path to the list.
elif grep -q '^ *var\\.paths:' {yml} 2>/dev/null; then
  sed -i '0,/^ *var\\.paths:/{{
    /^ *var\\.paths:/a\\      - {log_path}
  }}' {yml}
# Case: neither found — insert after "enabled: true" in syslog section.
else
  sed -i '0,/enabled: true/{{
    /enabled: true/a\\\\n    var.paths:\\n      - {log_path}
  }}' {yml}
fi

systemctl restart UTMStackModulesLogsCollector 2>/dev/null || true
echo "UTMstack filebeat config updated for {log_path}"
"""


async def perform_log_upload(agent_id: str, log_upload: LogUploadRequest) -> Dict[str, Any]:
    script = _build_log_upload_script(log_upload)
    result = execute_in_container(agent_id, script, timeout=30)

    if result.get("success"):
        # If this is a UTMstack container, update filebeat config to monitor the destination path
        metadata = read_agent_metadata(agent_id)
        siem_type = metadata.get("siem_type")
        if not siem_type:
            siem_type = detect_siem_type(agent_id)
        if siem_type == "utmstack":
            fb_script = _build_utmstack_filebeat_script(log_upload.destination_path)
            fb_result = execute_in_container(agent_id, fb_script, timeout=30)
            if fb_result.get("success"):
                logger.info(f"[{agent_id}] UTMstack filebeat configured for {log_upload.destination_path}")
            else:
                logger.warning(f"[{agent_id}] UTMstack filebeat config update failed: {fb_result.get('stderr', '')}")

    return result


async def run_log_schedule(schedule_id: str, agent_id: str, log_upload: LogUploadRequest,
                            interval_seconds: int, duration_seconds: Optional[int], indefinite: bool) -> None:
    start_time = time.time()
    scheduled_log_tasks[schedule_id]["status"] = "running"
    scheduled_log_tasks[schedule_id].setdefault("last_run", None)  # kept when resuming after a restart
    scheduled_log_tasks[schedule_id].setdefault("runs", 0)

    try:
        while True:
            if agent_id not in lxc.list_containers():
                scheduled_log_tasks[schedule_id]["status"] = "stopped"
                scheduled_log_tasks[schedule_id]["error"] = "Container not found"
                log_activity("log_schedule_stopped", {"schedule_id": schedule_id, "container_id": agent_id}, status="error")
                break

            result = await perform_log_upload(agent_id, log_upload)
            scheduled_log_tasks[schedule_id]["last_run"] = utc_now().isoformat()
            scheduled_log_tasks[schedule_id]["runs"] += 1
            if not result.get("success"):
                scheduled_log_tasks[schedule_id]["last_error"] = result.get("stderr") or result.get("error")

            if not indefinite and duration_seconds is not None:
                if time.time() - start_time >= duration_seconds:
                    scheduled_log_tasks[schedule_id]["status"] = "completed"
                    break

            await asyncio.sleep(interval_seconds)
    except asyncio.CancelledError:
        if scheduled_log_tasks[schedule_id].get("status") != INTERRUPTED:  # a restart: resumes afterwards
            scheduled_log_tasks[schedule_id]["status"] = "stopped"
    except Exception as e:
        scheduled_log_tasks[schedule_id]["status"] = "error"
        scheduled_log_tasks[schedule_id]["error"] = str(e)
        log_activity("log_schedule_failed", {"schedule_id": schedule_id, "container_id": agent_id, "error": str(e)}, status="error")


def schedule_public(schedule: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in schedule.items() if k not in ("task", "request")}


def interrupt_for_shutdown() -> None:
    """A stop began: interrupt running schedules (they resume at the next start)."""
    for schedule in list(scheduled_log_tasks.values()):
        if schedule.get("status") in ("running", "starting"):
            schedule["status_before_restart"] = schedule["status"]
            schedule["status"] = INTERRUPTED
            task = schedule.get("task")
            if task is not None and not task.done():
                task.get_loop().call_soon_threadsafe(task.cancel)


def resume_log_schedules() -> int:
    """At startup: restart schedules that were running when Habeny stopped, for the time they
    had left (indefinite ones indefinitely). Must run in the event loop."""
    resumed = 0
    for schedule_id, schedule in list(scheduled_log_tasks.items()):
        if (schedule.get("status") != INTERRUPTED or "request" not in schedule
                or schedule.get("status_before_restart") not in ("running", "starting")):
            continue
        remaining = None
        if not schedule.get("indefinite"):
            started = datetime.fromisoformat(schedule["created_at"])
            elapsed = (datetime.now(timezone.utc) - started).total_seconds()
            remaining = (schedule.get("duration_seconds") or 0) - elapsed
            if remaining <= 0:
                schedule["status"] = "completed"
                schedule["completed_note"] = "Its time ran out while Habeny was stopped"
                scheduled_log_tasks.save(schedule_id)
                continue
        schedule["status"] = "starting"
        schedule["resumed_at"] = utc_now().isoformat()
        schedule["resumes"] = schedule.get("resumes", 0) + 1
        scheduled_log_tasks.save(schedule_id)
        schedule["task"] = asyncio.create_task(run_log_schedule(
            schedule_id, schedule["agent_id"], LogUploadRequest(**schedule["request"]),
            schedule["interval_seconds"], remaining, bool(schedule.get("indefinite"))))
        resumed += 1
    if resumed:
        logger.info(f"Resumed {resumed} log schedule(s) after the restart")
    return resumed
