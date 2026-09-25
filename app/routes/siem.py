"""
Per-SIEM aggregate stats.
"""
import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException

from app.core.lxc_backend import lxc
from app.models import APIResponse
from app.services import tenancy
from app.services.agent_info import (
    detect_siem_type,
    get_agent_info,
    write_agent_metadata,
)
from app.services.auth import current_user
from app.state import simulations_db

logger = logging.getLogger(__name__)
router = APIRouter()


def summarize(infos: list[dict], simulations: list[dict]) -> list[dict]:
    """One row per SIEM type: its containers and agents, from the status each container
    reports, and what the SIEM detected in the latest checked attack simulation."""
    rows: dict[str, dict] = {}

    def row(siem: str) -> dict:
        return rows.setdefault(siem, {"siem_type": siem, "containers": 0, "running": 0, "agents_running": 0,
                                      "manager_reachable": 0, "detection_checks": 0, "last_detection": None})

    for info in infos:
        siem = info.get("siem_type")
        if not siem or siem in ("none", "unknown"):
            continue
        r = row(siem)
        r["containers"] += 1
        r["running"] += info.get("lifecycle_status") == "running"
        r["agents_running"] += bool(info.get("siem_agent_running"))
        r["manager_reachable"] += bool(info.get("manager_reachable"))

    for sim in simulations:
        found = sim.get("detection") or {}
        if found.get("status") != "done" or not found.get("siem"):
            continue
        r = row(found["siem"])
        r["detection_checks"] += 1
        last = r["last_detection"]
        if last is None or (found.get("checked_at") or "") > (last.get("checked_at") or ""):
            r["last_detection"] = {
                "simulation_id": sim.get("simulation_id"), "profile_id": sim.get("profile_id"),
                "manager_name": found.get("manager_name"), "checked_at": found.get("checked_at"),
                "detected": found.get("detected"), "containers": found.get("containers"),
                "detection_rate": found.get("detection_rate"), "missed": found.get("missed") or [],
            }
    return sorted(rows.values(), key=lambda r: r["siem_type"])


@router.get("/siem/summary", response_model=APIResponse)
async def get_siem_summary(user: dict | None = Depends(current_user)):
    """Per SIEM type: containers, running agents, agents that reach their manager, and the
    latest detection check (for the Dashboard)"""
    from app.routes.agents import _all_agent_infos  # the Containers list's parallel scan

    infos = await asyncio.to_thread(_all_agent_infos, user)
    sims = [s for s in list(simulations_db.values()) if tenancy.same_team(user, s.get("team_id"))]
    rows = summarize(infos, sims)
    return APIResponse(success=True, message=f"{len(rows)} SIEM types", data={"siems": rows})


@router.get("/siem/{siem_type}/stats", response_model=APIResponse)
async def get_siem_stats(siem_type: str, user: dict | None = Depends(current_user)):
    """Get statistics for a specific SIEM type"""
    try:
        if siem_type not in ["wazuh", "ossec", "utmstack", "elastic"]:
            raise HTTPException(status_code=400, detail=f"Invalid SIEM type: {siem_type}")
        requested_type = siem_type

        # Count agents for this SIEM
        agent_count = 0
        connected_count = 0

        for name in tenancy.visible(user, lxc.list_containers()):
            try:
                container = lxc.Container(name)
                agent_info = get_agent_info(container)
                agent_siem = agent_info.get("siem_type")

                if not agent_siem:
                    detected = detect_siem_type(name)
                    if detected and detected != "unknown":
                        agent_siem = detected
                        write_agent_metadata(name, {"siem_type": detected})

                if agent_siem == requested_type:
                    agent_count += 1
                    # As the container's own status check reports it, for every SIEM type
                    if agent_info.get("siem_agent_running") and agent_info.get("manager_reachable"):
                        connected_count += 1
            except Exception as e:
                logger.warning(f"Failed to inspect container {name}: {e}")
                continue

        return APIResponse(
            success=True,
            message=f"Stats for {requested_type} retrieved",
            data={
                "siem_type": requested_type,
                "total_agents": agent_count,
                "connected_agents": connected_count,
                "disconnected_agents": agent_count - connected_count,
                "connection_rate": round(connected_count / agent_count * 100, 2) if agent_count > 0 else 0
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(success=False, message="Failed to get SIEM stats", error=str(e))
