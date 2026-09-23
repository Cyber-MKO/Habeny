"""
Agent introspection — persisted container metadata, live container state and SIEM connectivity.
"""
import json
import logging
import os
import threading
import time
from typing import Any, Dict, Optional

import lxc

from app.config import AGENTS_DIR, DB_PATH
from app.core.container import get_container_stats
from app.core.shell import execute_in_container
from app.db import get_agent_by_name, get_or_create_agent_seq_id, mark_agent_deleted, upsert_agent
from app.models import utc_now

logger = logging.getLogger(__name__)


def read_agent_metadata(agent_name: str) -> Dict[str, Any]:
    """Load persisted container metadata from the database if available."""
    data = get_agent_by_name(DB_PATH, agent_name)
    if not data:
        return {}
    if "seq_id" in data and "agent_seq_id" not in data:
        data["agent_seq_id"] = data.get("seq_id")
    return data


def write_agent_metadata(agent_name: str, metadata: Dict[str, Any]) -> None:
    """Persist container metadata to the database for later lookup."""
    payload = {**read_agent_metadata(agent_name), **metadata}
    if "agent_seq_id" in payload and "seq_id" not in payload:
        payload["seq_id"] = payload.get("agent_seq_id")
    if "seq_id" not in payload or payload.get("seq_id") is None:
        payload["seq_id"] = get_or_create_agent_seq_id(DB_PATH, agent_name)
    payload["agent_seq_id"] = payload.get("seq_id")

    allowed_keys = {
        "seq_id",
        "siem_type",
        "siem_ip",
        "siem_version",
        "agent_group",
        "os_type",
        "config_template_id",
        "lifecycle_status",
        "state",
        "init_pid",
        "ip_addresses",
        "siem_agent_status",
        "siem_agent_running",
        "siem_agent_last_check",
        "manager_host",
        "manager_port",
        "manager_status",
        "manager_reachable",
        "created_at",
        "updated_at",
        "deleted_at"
    }
    db_payload = {key: payload.get(key) for key in allowed_keys if key in payload}
    upsert_agent(DB_PATH, agent_name, db_payload)


def delete_agent_metadata(agent_name: str) -> None:
    """Mark persisted metadata for a container as deleted."""
    try:
        mark_agent_deleted(DB_PATH, agent_name)
    except Exception as e:
        logger.warning(f"Failed to mark metadata deleted for {agent_name}: {e}")


def migrate_legacy_agent_metadata() -> None:
    """Migrate legacy container metadata JSON files into the database"""
    for legacy_file in AGENTS_DIR.glob("*.json"):
        try:
            with open(legacy_file, "r") as f:
                legacy_data = json.load(f)
            agent_name = legacy_data.get("agent_name") or legacy_data.get("agent_id") or legacy_file.stem
            write_agent_metadata(agent_name, legacy_data)
        except Exception as e:
            logger.warning(f"Failed to migrate {legacy_file}: {e}")


# Scanning every container's state costs a round-trip per running container, and
# several endpoints (system info, health, live metrics) need the same numbers.
# Share one scan for a couple of seconds; concurrent callers wait for it instead
# of each starting their own.
CONTAINER_SCAN_TTL = 2.0
_scan_lock = threading.Lock()
_scan_cache: Dict[str, Any] = {"at": 0.0, "value": None}


def container_state_summary() -> Dict[str, Any]:
    """Names, total, counts by state, and `running` (anything not STOPPED, like lxc's
    Container.running) from a single pass over all containers. Blocking: call it via
    asyncio.to_thread from async code."""
    with _scan_lock:
        cached = _scan_cache["value"]
        if cached is not None and time.monotonic() - _scan_cache["at"] < CONTAINER_SCAN_TTL:
            return cached
        names = lxc.list_containers()
        by_state = {"RUNNING": 0, "STOPPED": 0, "FROZEN": 0, "OTHER": 0}
        running = 0
        for name in names:
            state = lxc.Container(name).state
            by_state[state if state in by_state else "OTHER"] += 1
            if state and state != "STOPPED":
                running += 1
        summary = {"names": list(names), "total": len(names), "by_state": by_state, "running": running}
        _scan_cache.update(at=time.monotonic(), value=summary)
        return summary


def get_containers_by_state() -> Dict[str, int]:
    """Get container counts by state"""
    return dict(container_state_summary()["by_state"])


def get_agent_info(container, detailed: bool = False) -> dict:
    """Extract comprehensive container information from container"""
    info = {
        "agent_id": container.name,
        "agent_name": container.name,
        "lifecycle_status": "running" if container.running else "stopped",
        "state": container.state,
        "init_pid": container.init_pid,
        "ip_addresses": container.get_ips() if container.running else [],
    }

    metadata = read_agent_metadata(container.name)
    if metadata:
        for key in [
            "agent_seq_id",
            "siem_type",
            "siem_ip",
            "siem_version",
            "agent_group",
            "os_type",
            "created_at",
            "tags",
            "siem_agent_status",
            "siem_agent_running",
            "siem_agent_last_check",
            "manager_host",
            "manager_port",
            "manager_status",
            "manager_reachable"
        ]:
            value = metadata.get(key)
            if value is not None:
                info[key] = value

    # Try to extract SIEM metadata from container config
    # In production, store this in database
    try:
        config_file = container.config_file_name
        if os.path.exists(config_file):
            with open(config_file, 'r') as f:
                config_content = f.read().lower()
                if "wazuh" in config_content:
                    info["siem_type"] = "wazuh"
                elif "ossec" in config_content:
                    info["siem_type"] = "ossec"
                elif "ossim" in config_content:
                    info["siem_type"] = "ossim"
                elif "utmstack" in config_content:
                    info["siem_type"] = "utmstack"
                elif "elastic" in config_content:
                    info["siem_type"] = "elastic"
    except Exception:
        pass

    if container.running:
        status_result = execute_in_container(
            container.name,
            "cat /var/lib/siem-agent-status.json 2>/dev/null",
            timeout=5
        )
        if status_result.get("success") and status_result.get("stdout"):
            try:
                status_payload = json.loads(status_result["stdout"])
                info["siem_agent_status"] = status_payload.get("status")
                info["siem_agent_running"] = status_payload.get("running")
                info["siem_agent_last_check"] = status_payload.get("last_check")
                info["manager_host"] = status_payload.get("manager_host")
                info["manager_port"] = status_payload.get("manager_port")
                info["manager_status"] = status_payload.get("manager_status")
                info["manager_reachable"] = status_payload.get("manager_reachable")
                if status_payload.get("siem_type") and not info.get("siem_type"):
                    info["siem_type"] = status_payload.get("siem_type")
                write_agent_metadata(
                    container.name,
                    {
                        "siem_type": info.get("siem_type"),
                        "siem_agent_status": info.get("siem_agent_status"),
                        "siem_agent_running": info.get("siem_agent_running"),
                        "siem_agent_last_check": info.get("siem_agent_last_check"),
                        "manager_host": info.get("manager_host"),
                        "manager_port": info.get("manager_port"),
                        "manager_status": info.get("manager_status"),
                        "manager_reachable": info.get("manager_reachable"),
                    }
                )
            except json.JSONDecodeError:
                pass

    if detailed:
        info["stats"] = get_container_stats(container.name)
        info["siem_connectivity"] = check_siem_connectivity(container.name)

    write_agent_metadata(
        container.name,
        {
            "agent_seq_id": info.get("agent_seq_id"),
            "lifecycle_status": info.get("lifecycle_status"),
            "state": info.get("state"),
            "init_pid": info.get("init_pid"),
            "ip_addresses": info.get("ip_addresses")
        }
    )

    return info


def detect_siem_type(container_name: str) -> Optional[str]:
    """Detect SIEM type by checking installed agent artifacts."""
    try:
        container = lxc.Container(container_name)
        if not container.running:
            return None
        script = (
            "if [ -f /var/ossec/bin/wazuh-control ] || [ -f /var/ossec/bin/wazuh-agentd ]; then "
            "echo wazuh; "
            "elif [ -f /var/ossec/bin/ossec-control ] || [ -f /var/ossec/bin/ossec-agentd ]; then "
            "echo ossec; "
            "elif [ -f /usr/share/ossim/agent/agent.py ]; then "
            "echo ossim; "
            "elif [ -f /opt/utmstack-linux-agent/utmstack_agent_service ]; then "
            "echo utmstack; "
            "elif command -v elastic-agent >/dev/null 2>&1; then "
            "echo elastic; "
            "else echo unknown; fi"
        )
        result = execute_in_container(container_name, script, timeout=10)
        if result.get("success") and result.get("stdout"):
            return result["stdout"].strip().splitlines()[-1]
    except Exception:
        return None
    return None


def check_siem_connectivity(container_name: str) -> dict:
    """Check SIEM agent connectivity status"""
    try:
        container = lxc.Container(container_name)
        if not container.running:
            return {
                "status": "disconnected",
                "reason": "Container not running",
                "last_check": utc_now().isoformat()
            }

        # Check if Wazuh agent is running
        check_result = execute_in_container(
            container_name,
            "systemctl is-active wazuh-agent 2>/dev/null || service wazuh-agent status 2>/dev/null || echo 'unknown'",
            timeout=10
        )

        if "active" in check_result.get("stdout", "").lower():
            status = "connected"
        elif "inactive" in check_result.get("stdout", "").lower():
            status = "pending"
        else:
            status = "disconnected"

        return {
            "status": status,
            "last_check": utc_now().isoformat(),
            "agent_status": check_result.get("stdout", "").strip()
        }

    except Exception as e:
        return {
            "status": "error",
            "reason": str(e),
            "last_check": utc_now().isoformat()
        }
