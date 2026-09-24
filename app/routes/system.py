"""
System info and health endpoints.
"""
import asyncio
import logging
import os
import time
from multiprocessing import cpu_count

from fastapi import APIRouter, HTTPException

from app.config import BENCHMARK_WORKERS, DEPLOY_WORKERS
from app.core.common import get_lxc_default_config_path, get_lxc_version
from app.core.container import get_system_arch
from app.core.os_images import OS_IMAGES
from app.models import APIResponse, HealthCheckResponse, SIEMType
from app.services import alerts
from app.services.agent_info import container_state_summary
from app.services.simulation import list_simulation_profiles
from app.state import PROCESS_STARTED_AT, simulations_db
from app.version import __version__

logger = logging.getLogger(__name__)
router = APIRouter()


def _lxc_templates() -> list:
    try:
        return sorted(os.listdir("/usr/share/lxc/templates"))
    except OSError:
        return []


@router.get("/system/info", response_model=APIResponse)
async def system_info():
    """Get comprehensive system and LXC information"""
    try:
        containers = await asyncio.to_thread(container_state_summary)
        info = {
            "platform": {
                "name": "Multi-SIEM Container Emulation Platform",
                "version": __version__,
                "lxc_version": get_lxc_version(),
                "default_config_path": get_lxc_default_config_path(),
                "uptime_seconds": round(time.monotonic() - PROCESS_STARTED_AT, 1),
            },
            "system": {
                "arch": get_system_arch(),
                "is_root": os.geteuid() == 0,
                "cpu_count": cpu_count(),
                "worker_config": {
                    "deploy_workers": DEPLOY_WORKERS,
                    "benchmark_workers": BENCHMARK_WORKERS
                }
            },
            "containers": {
                "total": containers["total"],
                "by_state": dict(containers["by_state"]),
            },
            "supported_features": {
                "siem_types": [t.value for t in SIEMType if t != SIEMType.NONE],
                "os_types": list(OS_IMAGES),
                "simulation_profiles": list_simulation_profiles(),
                "parallel_modes": ["multiprocessing", "threading", "sequential"]
            },
            "templates": _lxc_templates(),
        }
        return APIResponse(success=True, message="System info retrieved", data=info)
    except Exception as e:
        logger.error(f"Failed to get system info: {e}")
        return APIResponse(success=False, message="Failed to get system info", error=str(e))


@router.get("/system/health", response_model=HealthCheckResponse)
async def health_check():
    """Platform summary for the Dashboard. status is "degraded" while a critical alert is
    active (e.g. LXC unavailable, disk nearly full), else "healthy"; /readyz is the probe."""
    try:
        containers = await asyncio.to_thread(container_state_summary)
        active = alerts.manager.active()
        critical = [a for a in active if a["severity"] == "critical"]

        return HealthCheckResponse(
            status="degraded" if critical else "healthy",
            version=__version__,
            uptime_seconds=round(time.monotonic() - PROCESS_STARTED_AT, 1),
            containers_count=containers["total"],
            system_info={
                "cpu_count": cpu_count(),
                "running_containers": containers["running"],
                "active_simulations": len([s for s in simulations_db.values() if s.get("status") == "running"]),
                "active_alerts": len(active),
                "critical_alerts": len(critical),
            }
        )
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail=f"Service unhealthy: {str(e)}")
