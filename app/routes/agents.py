"""
Container endpoints: deploy (+ live progress), list, stats, get, delete, bulk ops, start/stop, UTMstack syslog toggles.
"""
import asyncio
import json
import logging
import time
import uuid
from multiprocessing import cpu_count
from typing import Optional

import lxc
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from app.config import DB_PATH
from app.core.common import check_root
from app.core.shell import execute_in_container
from app.db import create_group, create_syslog_config, get_manager, get_or_create_agent_seq_id, group_exists
from app.models import AgentDeploymentRequest, APIResponse, BulkOperationRequest, utc_now
from app.services.activity import log_activity
from app.services.agent_info import container_counts, delete_agent_metadata, get_agent_info, write_agent_metadata
from app.services.deployment import (
    progress_event,
    progress_finish,
    progress_start,
    run_deployment_workers,
)
from app.state import deployment_progress, deployment_progress_lock

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/agents/deploy/progress/{deployment_id}", response_model=APIResponse)
async def get_deployment_progress(deployment_id: str):
    """Live progress (per-container steps and an activity feed) of a deployment"""
    with deployment_progress_lock:
        job = deployment_progress.get(deployment_id)
        if not job:
            raise HTTPException(status_code=404, detail="Deployment not found")
        data = json.loads(json.dumps(job, default=str))
    data["containers"] = list(data["containers"].values())
    return APIResponse(success=True, message=f"Deployment {data['status']}", data=data)


@router.post("/agents/deploy", response_model=APIResponse)
async def deploy_agents(
    deployment: AgentDeploymentRequest,
    background_tasks: BackgroundTasks,
    root: bool = Depends(check_root)
):
    """
    Deploy multiple containers with SIEM agents

    Supports Wazuh, OSSEC, OSSIM, and UTMstack with configurable parameters
    """
    deployment_id = deployment.deployment_id or str(uuid.uuid4())
    progress_start(deployment_id, deployment.count, str(getattr(deployment.siem_type, "value", deployment.siem_type)))
    progress_event(deployment_id, f"Deployment request received ({deployment.count} container{'s' if deployment.count != 1 else ''})")
    try:
        start_time = time.time()

        # If a manager profile is specified, load it and fill in any fields
        # the request didn't explicitly set
        if deployment.manager_profile_id:
            mgr = get_manager(DB_PATH, deployment.manager_profile_id)
            if not mgr:
                raise HTTPException(status_code=404, detail=f"Manager profile '{deployment.manager_profile_id}' not found")
            progress_event(deployment_id, f"Loaded manager profile '{mgr.get('name', deployment.manager_profile_id)}'")
            profile_fields = ["siem_type", "siem_ip", "siem_version", "siem_auth_key",
                            "os_type", "agent_group", "memory_limit", "cpu_shares", "config_template_id"]
            for field in profile_fields:
                req_val = getattr(deployment, field, None)
                mgr_val = mgr.get(field)
                # Use profile value when the request field is at its default/empty
                if mgr_val and (req_val is None or req_val == "" or
                    (field == "siem_type" and req_val == "wazuh") or
                    (field == "agent_group" and req_val == "default") or
                    (field == "os_type" and req_val == "ubuntu_22_04")):
                    setattr(deployment, field, mgr_val)

        # Validate: siem_ip required unless deploying bare containers
        if deployment.siem_type != "none" and not deployment.siem_ip:
            raise HTTPException(status_code=400, detail="siem_ip is required when deploying a SIEM agent")

        if deployment.agent_group:
            if not group_exists(DB_PATH, deployment.agent_group):
                if deployment.auto_create_group:
                    create_group(DB_PATH, deployment.agent_group, "Auto-created during deployment")
                    log_activity("group_auto_created", {"group": deployment.agent_group})
                    progress_event(deployment_id, f"Created group '{deployment.agent_group}'")
                else:
                    raise HTTPException(status_code=400, detail="Container group not found")

        # Log deployment request
        log_activity(
            "container_deployment_started",
            {
                "count": deployment.count,
                "siem_type": deployment.siem_type,
                "siem_ip": deployment.siem_ip,
                "os_type": deployment.os_type
            }
        )

        logger.info(f"Starting deployment of {deployment.count} {deployment.siem_type} containers")

        # Convert to dict for multiprocessing
        deployment_dict = {
            "siem_type": deployment.siem_type,
            "siem_ip": deployment.siem_ip,
            "siem_version": deployment.siem_version,
            "os_type": deployment.os_type,
            "agent_group": deployment.agent_group,
            "agent_base_name": deployment.agent_base_name,
            "memory_limit": deployment.memory_limit,
            "cpu_shares": deployment.cpu_shares,
            "config_template_id": deployment.config_template_id,
            "siem_auth_key": deployment.siem_auth_key
        }

        # Create container names
        agent_names = [f"{deployment.agent_base_name}-{i:04d}" for i in range(1, deployment.count + 1)]

        agent_seq_ids = {}
        for name in agent_names:
            progress_event(deployment_id, "Queued", container=name, status="pending")
            seq_id = get_or_create_agent_seq_id(DB_PATH, name)
            agent_seq_ids[name] = seq_id
            write_agent_metadata(
                name,
                {
                    "agent_seq_id": seq_id,
                    "siem_type": deployment.siem_type,
                    "siem_ip": deployment.siem_ip,
                    "siem_version": deployment.siem_version,
                    "agent_group": deployment.agent_group,
                    "os_type": deployment.os_type,
                    "config_template_id": deployment.config_template_id,
                    "lifecycle_status": "starting"
                }
            )

        # Deploy in parallel using multiprocessing, off the event loop so the
        # API (and progress polling) stays responsive during long deployments
        progress_event(deployment_id, f"Launching {min(cpu_count(), len(agent_names))} deployment workers")
        results, warnings = await asyncio.to_thread(
            run_deployment_workers, deployment_id, agent_names, deployment_dict, agent_seq_ids
        )

        elapsed_time = time.time() - start_time
        successful = [r for r in results if r["success"]]
        failed = [r for r in results if not r["success"]]

        # Log completion
        log_activity(
            "container_deployment_completed",
            {
                "total_requested": deployment.count,
                "successful": len(successful),
                "failed": len(failed),
                "elapsed_time": elapsed_time
            },
            status="success" if len(failed) == 0 else "partial"
        )
        progress_finish(
            deployment_id,
            "completed" if not failed else ("failed" if not successful else "partial"),
            f"Deployed {len(successful)}/{deployment.count} containers in {elapsed_time:.1f}s",
            level="success" if not failed else "error",
        )

        return APIResponse(
            success=len(failed) == 0,
            message=f"Deployed {len(successful)}/{deployment.count} containers in {elapsed_time:.2f}s",
            data={
                "deployment_id": deployment_id,
                "total_requested": deployment.count,
                "successful": len(successful),
                "failed": len(failed),
                "elapsed_time_seconds": round(elapsed_time, 2),
                "agents_per_second": round(len(successful) / elapsed_time, 2) if elapsed_time > 0 else 0,
                "deployed_agents": [r for r in results if r["success"]],
                "failed_agents": [r for r in results if not r["success"]],
                "warnings": warnings,
                "siem_mapping": {
                    "siem_type": deployment.siem_type,
                    "siem_ip": deployment.siem_ip,
                    "siem_version": deployment.siem_version,
                    "agent_group": deployment.agent_group
                }
            },
            error=f"{len(failed)} containers failed" if failed else None
        )

    except HTTPException as e:
        progress_finish(deployment_id, "failed", f"Deployment rejected: {e.detail}", level="error")
        raise
    except Exception as e:
        logger.error(f"Container deployment failed: {e}")
        log_activity("container_deployment_failed", {"error": str(e)}, status="error")
        progress_finish(deployment_id, "failed", f"Deployment failed: {e}", level="error")
        return APIResponse(success=False, message="Container deployment failed", error=str(e))


@router.get("/agents", response_model=APIResponse)
async def list_agents(
    siem_type: Optional[str] = Query(None, description="Filter by SIEM type"),
    status: Optional[str] = Query(None, description="Filter by status"),
    agent_group: Optional[str] = Query(None, description="Filter by container group"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0)
):
    """List all containers with filtering and pagination"""
    try:
        all_agents = []

        for name in lxc.list_containers():
            container = lxc.Container(name)
            agent_info = get_agent_info(container)

            # Apply filters
            if siem_type and agent_info.get("siem_type") != siem_type:
                continue
            if status and agent_info.get("lifecycle_status") != status:
                continue
            if agent_group and agent_info.get("agent_group") != agent_group:
                continue

            all_agents.append(agent_info)

        # Pagination
        total = len(all_agents)
        paginated_agents = all_agents[offset:offset + limit]

        return APIResponse(
            success=True,
            message=f"Retrieved {len(paginated_agents)} containers",
            data={
                "agents": paginated_agents,
                "total": total,
                "limit": limit,
                "offset": offset,
                "has_more": offset + limit < total
            }
        )

    except Exception as e:
        logger.error(f"Failed to list containers: {e}")
        return APIResponse(success=False, message="Failed to list containers", error=str(e))


@router.get("/agents/stats", response_model=APIResponse)
async def get_agents_stats():
    """Get aggregated container statistics"""
    try:
        counts = await asyncio.to_thread(container_counts)
        return APIResponse(
            success=True,
            message="Container statistics retrieved",
            data={
                "total_agents": counts["total"],
                "by_siem_type": counts["by_siem_type"],
                "by_status": {"running": counts["running"], "stopped": counts["stopped"], "error": 0},
                "timestamp": utc_now().isoformat()
            }
        )

    except Exception as e:
        logger.error(f"Failed to get container stats: {e}")
        return APIResponse(success=False, message="Failed to get container statistics", error=str(e))


@router.get("/agents/{agent_id}", response_model=APIResponse)
async def get_agent(agent_id: str):
    """Get detailed information about a specific container"""
    try:
        if agent_id not in lxc.list_containers():
            raise HTTPException(status_code=404, detail=f"Container '{agent_id}' not found")

        container = lxc.Container(agent_id)
        agent_info = get_agent_info(container, detailed=True)

        return APIResponse(
            success=True,
            message=f"Container '{agent_id}' details retrieved",
            data=agent_info
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get container {agent_id}: {e}")
        return APIResponse(success=False, message="Failed to get container details", error=str(e))


@router.delete("/agents/{agent_id}", response_model=APIResponse)
async def delete_agent(agent_id: str, root: bool = Depends(check_root)):
    """Delete a container and optionally unregister from SIEM"""
    try:
        if agent_id not in lxc.list_containers():
            raise HTTPException(status_code=404, detail=f"Container '{agent_id}' not found")

        container = lxc.Container(agent_id)

        # Stop container if running
        if container.running:
            if not container.shutdown(10):
                container.stop()
            container.wait("STOPPED", 10)

        # Destroy container
        success = container.destroy()

        if success:
            log_activity("container_deleted", {"container_id": agent_id})
            delete_agent_metadata(agent_id)
            return APIResponse(
                success=True,
                message=f"Container '{agent_id}' deleted successfully"
            )
        else:
            return APIResponse(
                success=False,
                message=f"Failed to delete container '{agent_id}'",
                error="Destroy operation failed"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete container {agent_id}: {e}")
        return APIResponse(success=False, message="Failed to delete container", error=str(e))


@router.post("/agents/bulk/{operation}", response_model=APIResponse)
async def bulk_agent_operation(
    operation: str,
    request: BulkOperationRequest,
    root: bool = Depends(check_root)
):
    """Perform bulk operations on multiple containers"""
    try:
        if operation not in ['start', 'stop', 'delete']:
            raise HTTPException(status_code=400, detail=f"Invalid operation: {operation}")

        results = []

        for agent_id in request.container_names:
            try:
                if agent_id not in lxc.list_containers():
                    results.append({"agent_id": agent_id, "success": False, "error": "Not found"})
                    continue

                container = lxc.Container(agent_id)

                if operation == "start":
                    success = container.start() if not container.running else False
                elif operation == "stop":
                    success = container.shutdown(10) if container.running else False
                elif operation == "delete":
                    if container.running:
                        container.stop()
                        container.wait("STOPPED", 10)
                    success = container.destroy()
                    if success:
                        delete_agent_metadata(agent_id)

                results.append({"agent_id": agent_id, "success": success})

            except Exception as e:
                results.append({"agent_id": agent_id, "success": False, "error": str(e)})

        successful = sum(1 for r in results if r["success"])
        log_activity(f"bulk_{operation}", {
            "total": len(request.container_names),
            "successful": successful
        })

        return APIResponse(
            success=successful == len(request.container_names),
            message=f"Bulk {operation}: {successful}/{len(request.container_names)} successful",
            data={"results": results}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Bulk operation failed: {e}")
        return APIResponse(success=False, message="Bulk operation failed", error=str(e))


@router.post("/agents/{agent_id}/start", response_model=APIResponse)
async def start_agent(agent_id: str, root: bool = Depends(check_root)):
    """Start a container"""
    try:
        if agent_id not in lxc.list_containers():
            raise HTTPException(status_code=404, detail=f"Container '{agent_id}' not found")

        container = lxc.Container(agent_id)

        if container.running:
            return APIResponse(
                success=False,
                message=f"Container '{agent_id}' is already running"
            )

        success = container.start()
        if success:
            container.wait("RUNNING", 10)
            log_activity("container_started", {"container_id": agent_id})
            return APIResponse(
                success=True,
                message=f"Container '{agent_id}' started successfully"
            )
        else:
            return APIResponse(
                success=False,
                message=f"Failed to start container '{agent_id}'",
                error="Start operation failed"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start container {agent_id}: {e}")
        return APIResponse(success=False, message="Failed to start container", error=str(e))


@router.post("/agents/{agent_id}/stop", response_model=APIResponse)
async def stop_agent(agent_id: str, root: bool = Depends(check_root)):
    """Stop a container"""
    try:
        if agent_id not in lxc.list_containers():
            raise HTTPException(status_code=404, detail=f"Container '{agent_id}' not found")

        container = lxc.Container(agent_id)

        if not container.running:
            return APIResponse(
                success=False,
                message=f"Container '{agent_id}' is not running"
            )

        if not container.shutdown(10):
            container.stop()

        container.wait("STOPPED", 10)
        log_activity("container_stopped", {"container_id": agent_id})

        return APIResponse(
            success=True,
            message=f"Container '{agent_id}' stopped successfully"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to stop container {agent_id}: {e}")
        return APIResponse(success=False, message="Failed to stop container", error=str(e))


@router.post("/agents/{agent_id}/enable-syslog", response_model=APIResponse)
async def enable_utmstack_syslog(agent_id: str, protocol: str = Query("tcp")):
    """Enable syslog on a UTMstack container (port 7014) and create a syslog config profile"""
    try:
        if agent_id not in lxc.list_containers():
            raise HTTPException(status_code=404, detail=f"Container {agent_id} not found")

        proto = protocol.lower()
        if proto not in ("tcp", "udp"):
            raise HTTPException(status_code=400, detail="Protocol must be tcp or udp")

        cmd = f"/opt/utmstack-linux-agent/utmstack_agent_service enable-integration syslog {proto}"
        result = execute_in_container(agent_id, cmd, timeout=30)

        if not result.get("success"):
            return APIResponse(success=False, message="Failed to enable syslog", error=result.get("stderr", ""))

        # Get the container's IP for the syslog config profile
        container = lxc.Container(agent_id)
        ips = container.get_ips() if container.running else []
        agent_ip = ips[0] if ips else agent_id

        # Auto-create a syslog config profile for this listener
        profile_name = f"{agent_id}-syslog-{proto}"
        config_id = str(uuid.uuid4())
        try:
            create_syslog_config(DB_PATH, config_id, {
                "name": profile_name,
                "description": f"Auto-created: syslog {proto.upper()} on {agent_id} port 7014",
                "target_ip": agent_ip,
                "target_port": 7014,
                "protocol": proto,
                "siem_type": "utmstack",
            })
        except Exception:
            pass  # profile may already exist from a previous enable

        log_activity("utmstack_syslog_enabled", {"agent_id": agent_id, "protocol": proto})
        return APIResponse(success=True, message=f"Syslog {proto.upper()} enabled on {agent_id} (port 7014)", data={
            "agent_id": agent_id, "protocol": proto, "port": 7014,
            "syslog_config_profile": profile_name,
            "target_ip": agent_ip,
            "output": result.get("stdout", ""),
        })
    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(success=False, message="Failed to enable syslog", error=str(e))


@router.post("/agents/{agent_id}/disable-syslog", response_model=APIResponse)
async def disable_utmstack_syslog(agent_id: str, protocol: str = Query("tcp")):
    """Disable syslog on a UTMstack container"""
    try:
        if agent_id not in lxc.list_containers():
            raise HTTPException(status_code=404, detail=f"Container {agent_id} not found")

        proto = protocol.lower()
        if proto not in ("tcp", "udp"):
            raise HTTPException(status_code=400, detail="Protocol must be tcp or udp")

        cmd = f"/opt/utmstack-linux-agent/utmstack_agent_service disable-integration syslog {proto}"
        result = execute_in_container(agent_id, cmd, timeout=30)

        if not result.get("success"):
            return APIResponse(success=False, message="Failed to disable syslog", error=result.get("stderr", ""))

        log_activity("utmstack_syslog_disabled", {"agent_id": agent_id, "protocol": proto})
        return APIResponse(success=True, message=f"Syslog {proto.upper()} disabled on {agent_id}", data={
            "agent_id": agent_id, "protocol": proto, "output": result.get("stdout", ""),
        })
    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(success=False, message="Failed to disable syslog", error=str(e))
