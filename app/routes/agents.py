"""
Container endpoints: deploy (+ live progress), list, stats, get, delete, bulk ops, start/stop, UTMstack syslog toggles.
"""
import asyncio
import json
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from app.config import DB_PATH
from app.core.common import check_root
from app.core.lxc_backend import lxc
from app.core.shell import execute_in_container
from app.db import create_group, get_manager, get_or_create_agent_seq_id, group_exists
from app.models import AgentDeploymentRequest, APIResponse, BulkOperationRequest, utc_now
from app.services import licensing, tenancy
from app.services.activity import log_activity
from app.services.agent_info import container_counts, delete_agent_metadata, get_agent_info, write_agent_metadata
from app.services.auth import current_user
from app.services.deployment import (
    progress_event,
    progress_finish,
    progress_start,
    run_deployment_workers,
    worker_count,
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


def _announce_deployment(deployment_id: str, outcome: str, requested: int, successful: int, failed: int,
                         elapsed: float, siem_type: str, error: str | None) -> None:
    """Metrics, the deploy_failed alert and the deployment.finished notification."""
    from app.services import alerts, notify, telemetry
    try:
        telemetry.DEPLOYMENTS.inc(result=outcome)
        telemetry.CONTAINERS_DEPLOYED.inc(successful, result="success")
        telemetry.CONTAINERS_DEPLOYED.inc(failed, result="failure")
        alerts.deployment_finished(deployment_id, requested, successful, failed, error)
        notify.emit(
            "deployment.finished",
            f"Deployment {'succeeded' if outcome == 'completed' else 'partly failed' if outcome == 'partial' else 'failed'}: "
            f"{successful}/{requested} containers",
            f"First error: {error}" if error else "",
            level={"completed": "success", "partial": "warning"}.get(outcome, "error"),
            fields={"deployment_id": deployment_id, "siem_type": siem_type, "successful": successful,
                    "failed": failed, "duration": f"{elapsed:.0f} s"},
            link="/deploy",
        )
    except Exception:
        logger.exception("Announcing the deployment result failed")


@router.post("/agents/deploy", response_model=APIResponse)
async def deploy_agents(
    deployment: AgentDeploymentRequest,
    background_tasks: BackgroundTasks,
    root: bool = Depends(check_root),
    user: dict | None = Depends(current_user),
):
    """
    Deploy multiple containers with SIEM agents

    Supports Wazuh, OSSEC, UTMstack and Elastic with configurable parameters
    """
    deployment_id = deployment.deployment_id or str(uuid.uuid4())
    progress_start(deployment_id, deployment.count, str(getattr(deployment.siem_type, "value", deployment.siem_type)))
    progress_event(deployment_id, f"Deployment request received ({deployment.count} container{'s' if deployment.count != 1 else ''})")
    try:
        licensing.require()
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

        # A manager profile saved before OSSIM support was removed can still name it
        if str(getattr(deployment.siem_type, "value", deployment.siem_type)) == "ossim":
            raise HTTPException(status_code=400, detail="OSSIM is no longer supported (the product was retired in "
                                "2024). Change the manager profile's SIEM type.")

        # Validate: siem_ip required unless deploying bare containers
        if deployment.siem_type != "none" and not deployment.siem_ip:
            raise HTTPException(status_code=400, detail="siem_ip is required when deploying a SIEM agent")
        if deployment.siem_type in ("utmstack", "elastic") and not deployment.siem_auth_key:
            detail = ("The manager profile's auth key can't be read (the secret key changed?); re-enter it in the profile"
                      if deployment.manager_profile_id else "siem_auth_key is required for UTMstack and Elastic deployments")
            raise HTTPException(status_code=400, detail=detail)

        if deployment.agent_group and not group_exists(DB_PATH, deployment.agent_group):
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

        # Team and user limits; then the new containers belong to this user and their team
        # (names that already exist fail to deploy and keep their owner)
        existing = set(await asyncio.to_thread(lxc.list_containers))
        new_names = [n for n in agent_names if n not in existing]
        licensing.require(adding=len(new_names), existing=len(existing))
        tenancy.check_quota(user, len(new_names), list(existing))
        tenancy.record(new_names, user)

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
        mode = getattr(deployment.parallel_mode, "value", deployment.parallel_mode)
        workers = worker_count(mode, len(agent_names))
        progress_event(deployment_id, f"Launching {workers} deployment worker{'s' if workers != 1 else ''} ({mode})")
        results, warnings = await asyncio.to_thread(
            run_deployment_workers, deployment_id, agent_names, deployment_dict, agent_seq_ids, mode
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
        outcome = "completed" if not failed else ("failed" if not successful else "partial")
        progress_finish(
            deployment_id, outcome,
            f"Deployed {len(successful)}/{deployment.count} containers in {elapsed_time:.1f}s",
            level="success" if not failed else "error",
        )
        _announce_deployment(deployment_id, outcome, deployment.count, len(successful), len(failed), elapsed_time,
                             str(getattr(deployment.siem_type, "value", deployment.siem_type)),
                             failed[0].get("error") if failed else None)

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
        _announce_deployment(deployment_id, "failed", deployment.count, 0, deployment.count, 0,
                             str(getattr(deployment.siem_type, "value", deployment.siem_type)), str(e))
        return APIResponse(success=False, message="Container deployment failed", error=str(e))


LIST_PARALLELISM = 16


def _visible_container(name: str, user: dict | None) -> bool:
    """Exists and this user may see it (another team's container reads as not found)."""
    return name in lxc.list_containers() and tenancy.can_see(user, name)


def _all_agent_infos(user: dict | None = None) -> list:
    names = tenancy.visible(user, lxc.list_containers())
    with ThreadPoolExecutor(max_workers=min(LIST_PARALLELISM, max(1, len(names)))) as pool:
        return list(pool.map(lambda name: get_agent_info(lxc.Container(name)), names))


@router.get("/agents", response_model=APIResponse)
async def list_agents(
    siem_type: str | None = Query(None, description="Filter by SIEM type"),
    status: str | None = Query(None, description="Filter by status"),
    agent_group: str | None = Query(None, description="Filter by container group"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    user: dict | None = Depends(current_user),
):
    """List the containers you can see (all for admins; your team's otherwise), filtered and paged"""
    try:
        # Blocking (LXC calls, one lxc-attach per running container): in a thread so the rest
        # of the API stays responsive, and container by container in parallel
        infos = await asyncio.to_thread(_all_agent_infos, user)
        owners = await asyncio.to_thread(tenancy.owners, [i.get("agent_name") for i in infos])
        for info in infos:
            info["team_id"] = (owners.get(info.get("agent_name")) or {}).get("team_id")
        all_agents = [
            info for info in infos
            if (not siem_type or info.get("siem_type") == siem_type)
            and (not status or info.get("lifecycle_status") == status)
            and (not agent_group or info.get("agent_group") == agent_group)
        ]

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
async def get_agents_stats(user: dict | None = Depends(current_user)):
    """Container totals (for your team's containers unless you're an admin)"""
    try:
        if tenancy.is_unrestricted(user):
            counts = await asyncio.to_thread(container_counts)
        else:
            counts = await asyncio.to_thread(
                lambda: container_counts(tenancy.visible(user, lxc.list_containers())))
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
async def get_agent(agent_id: str, user: dict | None = Depends(current_user)):
    """Get detailed information about a specific container"""
    try:
        if not _visible_container(agent_id, user):
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
async def delete_agent(agent_id: str, root: bool = Depends(check_root), user: dict | None = Depends(current_user)):
    """Delete a container and optionally unregister from SIEM"""
    try:
        if not _visible_container(agent_id, user):
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
    root: bool = Depends(check_root),
    user: dict | None = Depends(current_user),
):
    """Perform bulk operations on multiple containers"""
    try:
        if operation not in ['start', 'stop', 'delete']:
            raise HTTPException(status_code=400, detail=f"Invalid operation: {operation}")

        results = []
        existing = set(tenancy.visible(user, lxc.list_containers()))  # once, not per container

        for agent_id in request.container_names:
            try:
                if agent_id not in existing:
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
            "successful": successful,
            "containers": request.container_names[:200],
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
async def start_agent(agent_id: str, root: bool = Depends(check_root), user: dict | None = Depends(current_user)):
    """Start a container"""
    try:
        if not _visible_container(agent_id, user):
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
async def stop_agent(agent_id: str, root: bool = Depends(check_root), user: dict | None = Depends(current_user)):
    """Stop a container"""
    try:
        if not _visible_container(agent_id, user):
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
async def enable_utmstack_syslog(agent_id: str, protocol: str = Query("tcp"), user: dict | None = Depends(current_user)):
    """Turn on a UTMstack container's syslog listener (port 7014), so it can receive syslog simulations"""
    try:
        if not _visible_container(agent_id, user):
            raise HTTPException(status_code=404, detail=f"Container '{agent_id}' not found")

        proto = protocol.lower()
        if proto not in ("tcp", "udp"):
            raise HTTPException(status_code=400, detail="Protocol must be tcp or udp")

        cmd = f"/opt/utmstack-linux-agent/utmstack_agent_service enable-integration syslog {proto}"
        result = execute_in_container(agent_id, cmd, timeout=30)

        if not result.get("success"):
            return APIResponse(success=False, message="Failed to enable syslog", error=result.get("stderr", ""))

        container = lxc.Container(agent_id)
        ips = container.get_ips() if container.running else []
        # Remembered on the container, so syslog simulations can offer it as a destination
        write_agent_metadata(agent_id, {"syslog_listener": proto})

        log_activity("utmstack_syslog_enabled", {"agent_id": agent_id, "protocol": proto})
        return APIResponse(success=True, message=f"Syslog {proto.upper()} enabled on {agent_id} (port 7014)", data={
            "agent_id": agent_id, "protocol": proto, "port": 7014,
            "target_ip": ips[0] if ips else None,
            "output": result.get("stdout", ""),
        })
    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(success=False, message="Failed to enable syslog", error=str(e))


@router.post("/agents/{agent_id}/disable-syslog", response_model=APIResponse)
async def disable_utmstack_syslog(agent_id: str, protocol: str = Query("tcp"), user: dict | None = Depends(current_user)):
    """Turn off a UTMstack container's syslog listener"""
    try:
        if not _visible_container(agent_id, user):
            raise HTTPException(status_code=404, detail=f"Container '{agent_id}' not found")

        proto = protocol.lower()
        if proto not in ("tcp", "udp"):
            raise HTTPException(status_code=400, detail="Protocol must be tcp or udp")

        cmd = f"/opt/utmstack-linux-agent/utmstack_agent_service disable-integration syslog {proto}"
        result = execute_in_container(agent_id, cmd, timeout=30)

        if not result.get("success"):
            return APIResponse(success=False, message="Failed to disable syslog", error=result.get("stderr", ""))

        write_agent_metadata(agent_id, {"syslog_listener": None})
        log_activity("utmstack_syslog_disabled", {"agent_id": agent_id, "protocol": proto})
        return APIResponse(success=True, message=f"Syslog {proto.upper()} disabled on {agent_id}", data={
            "agent_id": agent_id, "protocol": proto, "output": result.get("stdout", ""),
        })
    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(success=False, message="Failed to disable syslog", error=str(e))
