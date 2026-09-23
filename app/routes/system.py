"""
Root and system info/health endpoints.
"""
import logging
import os
import time
from multiprocessing import cpu_count

import lxc
from fastapi import APIRouter, HTTPException

from app.config import MAX_WORKERS
from app.core.common import get_lxc_default_config_path, get_lxc_version
from app.services.agent_info import get_containers_by_state
from app.services.simulation import list_simulation_profiles
from app.state import simulations_db
from models import APIResponse, HealthCheckResponse
from utils import get_system_arch, run_command

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/", response_model=APIResponse)
async def root():
    """Root endpoint with comprehensive API information"""
    return APIResponse(
        success=True,
        message="Multi-SIEM Container Emulation Platform API",
        data={
            "version": "2.0.0",
            "description": "LXC-based platform for deploying containers that run SIEM agents at scale",
            "supported_siem_types": ["wazuh", "ossec", "ossim", "utmstack", "elastic"],
            "default_os": "ubuntu_22_04",
            "max_workers": MAX_WORKERS,
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


@router.get("/system/info", response_model=APIResponse)
async def system_info():
    """Get comprehensive system and LXC information"""
    try:
        info = {
            "platform": {
                "name": "Multi-SIEM Container Emulation Platform",
                "version": "2.0.0",
                "lxc_version": get_lxc_version(),
                "default_config_path": get_lxc_default_config_path(),
            },
            "system": {
                "arch": get_system_arch(),
                "is_root": os.geteuid() == 0,
                "cpu_count": cpu_count(),
                "worker_config": {
                    "thread_workers": MAX_WORKERS,
                    "process_workers": cpu_count()
                }
            },
            "containers": {
                "total": len(lxc.list_containers()),
                "by_state": get_containers_by_state()
            },
            "supported_features": {
                "siem_types": ["wazuh", "ossec", "ossim", "utmstack", "elastic"],
                "os_types": ["ubuntu_22_04", "ubuntu_20_04", "debian_11"],
                "simulation_profiles": list_simulation_profiles(),
                "parallel_modes": ["multiprocessing", "threading", "sequential"]
            },
            "templates": run_command(["ls", "/usr/share/lxc/templates"])["stdout"].split()
        }
        return APIResponse(success=True, message="System info retrieved", data=info)
    except Exception as e:
        logger.error(f"Failed to get system info: {e}")
        return APIResponse(success=False, message="Failed to get system info", error=str(e))


@router.get("/system/health", response_model=HealthCheckResponse)
async def health_check():
    """Comprehensive health check endpoint"""
    try:
        containers = lxc.list_containers()
        running_containers = sum(1 for name in containers if lxc.Container(name).running)

        # Calculate uptime (simplified - use actual process start time in production)
        uptime = time.time()  # Placeholder

        return HealthCheckResponse(
            status="healthy",
            version="2.0.0",
            uptime_seconds=uptime,
            containers_count=len(containers),
            system_info={
                "cpu_count": cpu_count(),
                "running_containers": running_containers,
                "active_simulations": len([s for s in simulations_db.values() if s.get("status") == "running"])
            }
        )
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail=f"Service unhealthy: {str(e)}")
