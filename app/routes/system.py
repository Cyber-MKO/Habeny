"""
Root and system info/health endpoints.
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
from app.models import APIResponse, HealthCheckResponse
from app.services.agent_info import container_state_summary
from app.services.simulation import list_simulation_profiles
from app.state import PROCESS_STARTED_AT, simulations_db
from app.version import __version__

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/", response_model=APIResponse)
async def root():
    """Root endpoint with comprehensive API information"""
    return APIResponse(
        success=True,
        message="Multi-SIEM Container Emulation Platform API",
        data={
            "version": __version__,
            "description": "LXC-based platform for deploying containers that run SIEM agents at scale",
            "supported_siem_types": ["wazuh", "ossec", "utmstack", "elastic"],
            "default_os": "ubuntu_22_04",
            "max_workers": DEPLOY_WORKERS,
            "cpu_count": cpu_count(),
            "endpoint_groups": {
                "system": ["/system/info", "/system/health"],
                "containers": ["/agents", "/agents/deploy", "/agents/{id}", "/agents/stats"],
                "simulations": ["/simulations", "/simulations/start", "/simulations/load", "/simulations/syslog/start", "/simulations/stop"],
                "configs": ["/configs", "/configs/import", "/configs/export/{id}"],
                "reports": ["/reports", "/reports/generate", "/reports/{id}"],
                "activity": ["/activity/logs"],
                "siem": ["/siem/{siem_type}/stats"],
                "groups": ["/groups", "/groups/{group_name}/assign", "/groups/{group_name}/remove"]
            }
        }
    )


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
                "siem_types": ["wazuh", "ossec", "utmstack", "elastic"],
                "os_types": ["ubuntu_22_04", "ubuntu_20_04", "debian_11"],
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
    """Comprehensive health check endpoint"""
    try:
        containers = await asyncio.to_thread(container_state_summary)

        return HealthCheckResponse(
            status="healthy",
            version=__version__,
            uptime_seconds=round(time.monotonic() - PROCESS_STARTED_AT, 1),
            containers_count=containers["total"],
            system_info={
                "cpu_count": cpu_count(),
                "running_containers": containers["running"],
                "active_simulations": len([s for s in simulations_db.values() if s.get("status") == "running"])
            }
        )
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail=f"Service unhealthy: {str(e)}")
