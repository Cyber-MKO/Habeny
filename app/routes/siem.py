"""
Per-SIEM aggregate stats.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException

from app.core.lxc_backend import lxc
from app.models import APIResponse
from app.services import tenancy
from app.services.agent_info import (
    check_siem_connectivity,
    detect_siem_type,
    get_agent_info,
    write_agent_metadata,
)
from app.services.auth import current_user

logger = logging.getLogger(__name__)
router = APIRouter()


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
                    connectivity = check_siem_connectivity(name)
                    if connectivity.get("status") == "connected":
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
