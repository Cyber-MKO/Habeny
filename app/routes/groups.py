"""
Container group management, including group-wide bulk ops and log uploads.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException

from app.config import DB_PATH
from app.core.lxc_backend import lxc
from app.db import (
    assign_agents_to_group,
    create_group,
    delete_group,
    get_agents_in_group,
    get_or_create_agent_seq_id,
    group_exists,
    list_groups,
    remove_agents_from_group,
    rename_group,
)
from app.models import (
    APIResponse,
    BulkOperationRequest,
    GroupAgentRequest,
    GroupCreateRequest,
    GroupRenameRequest,
    LogScheduleRequest,
    LogUploadRequest,
)
from app.routes.agents import bulk_agent_operation
from app.routes.logs import schedule_log_upload
from app.services import tenancy
from app.services.activity import log_activity
from app.services.auth import current_user
from app.services.logs import perform_log_upload

logger = logging.getLogger(__name__)
router = APIRouter()


def _visible_members(data: dict, user: dict | None) -> dict:
    """Group counts include only the containers this user can see."""
    groups = []
    for group in data.get("groups", []):
        members = tenancy.visible(user, get_agents_in_group(DB_PATH, group["name"]))
        groups.append({**group, "agent_count": len(members)})
    return {**data, "groups": groups}


@router.get("/groups", response_model=APIResponse)
async def list_agent_groups(user: dict | None = Depends(current_user)):
    """List all container groups with counts (of the containers you can see)."""
    try:
        data = list_groups(DB_PATH)
        if not tenancy.is_unrestricted(user):
            data = _visible_members(data, user)
        return APIResponse(success=True, message="Groups retrieved", data=data)
    except Exception as e:
        logger.error(f"Failed to list groups: {e}")
        return APIResponse(success=False, message="Failed to list groups", error=str(e))


@router.post("/groups", response_model=APIResponse)
async def create_agent_group(request: GroupCreateRequest):
    """Create a new container group."""
    try:
        if group_exists(DB_PATH, request.name):
            raise HTTPException(status_code=400, detail="Group already exists")
        group = create_group(DB_PATH, request.name, request.description)
        log_activity("group_created", {"group": request.name})
        return APIResponse(success=True, message="Group created", data=group)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create group: {e}")
        return APIResponse(success=False, message="Failed to create group", error=str(e))


@router.post("/groups/{group_name}/rename", response_model=APIResponse)
async def rename_agent_group(group_name: str, request: GroupRenameRequest):
    """Rename a container group."""
    try:
        if not group_exists(DB_PATH, group_name):
            raise HTTPException(status_code=404, detail="Group not found")
        result = rename_group(DB_PATH, group_name, request.new_name, request.description)
        log_activity("group_renamed", {"group": group_name, "new_name": request.new_name})
        return APIResponse(success=True, message="Group renamed", data=result)
    except HTTPException:
        raise
    except ValueError as e:
        return APIResponse(success=False, message="Failed to rename group", error=str(e))
    except Exception as e:
        logger.error(f"Failed to rename group: {e}")
        return APIResponse(success=False, message="Failed to rename group", error=str(e))


@router.delete("/groups/{group_name}", response_model=APIResponse)
async def delete_agent_group(group_name: str):
    """Delete a container group and unassign containers."""
    try:
        if not group_exists(DB_PATH, group_name):
            raise HTTPException(status_code=404, detail="Group not found")
        removed = delete_group(DB_PATH, group_name)
        log_activity("group_deleted", {"group": group_name, "removed_containers": removed})
        return APIResponse(success=True, message="Group deleted", data={"group": group_name, "removed_containers": removed})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete group: {e}")
        return APIResponse(success=False, message="Failed to delete group", error=str(e))


@router.post("/groups/{group_name}/assign", response_model=APIResponse)
async def assign_group_agents(group_name: str, request: GroupAgentRequest,
                              user: dict | None = Depends(current_user)):
    """Assign containers to a group."""
    try:
        if not group_exists(DB_PATH, group_name):
            raise HTTPException(status_code=404, detail="Group not found")
        existing = set(tenancy.visible(user, lxc.list_containers()))
        valid_agent_ids = [agent_id for agent_id in request.agent_ids if agent_id in existing]
        invalid_agent_ids = [agent_id for agent_id in request.agent_ids if agent_id not in existing]

        for agent_id in valid_agent_ids:
            get_or_create_agent_seq_id(DB_PATH, agent_id)

        updated = assign_agents_to_group(DB_PATH, group_name, valid_agent_ids)
        log_activity("group_assign", {"group": group_name, "containers": request.agent_ids})
        return APIResponse(
            success=True,
            message=f"Assigned {updated} containers to {group_name}",
            data={
                "group": group_name,
                "assigned": updated,
                "invalid_containers": invalid_agent_ids
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to assign group: {e}")
        return APIResponse(success=False, message="Failed to assign group", error=str(e))


@router.post("/groups/{group_name}/remove", response_model=APIResponse)
async def remove_group_agents(group_name: str, request: GroupAgentRequest,
                              user: dict | None = Depends(current_user)):
    """Remove containers from a group."""
    try:
        if not group_exists(DB_PATH, group_name):
            raise HTTPException(status_code=404, detail="Group not found")
        updated = remove_agents_from_group(DB_PATH, tenancy.visible(user, request.agent_ids))
        log_activity("group_remove", {"group": group_name, "containers": request.agent_ids})
        return APIResponse(
            success=True,
            message=f"Removed {updated} containers from {group_name}",
            data={"group": group_name, "removed": updated}
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to remove from group: {e}")
        return APIResponse(success=False, message="Failed to remove group", error=str(e))


@router.post("/groups/{group_name}/bulk/{operation}", response_model=APIResponse)
async def bulk_group_operation(group_name: str, operation: str, user: dict | None = Depends(current_user)):
    """Perform bulk operations on all containers in a group."""
    try:
        if operation not in ['start', 'stop', 'delete']:
            raise HTTPException(status_code=400, detail=f"Invalid operation: {operation}")
        if not group_exists(DB_PATH, group_name):
            raise HTTPException(status_code=404, detail="Group not found")

        agent_ids = tenancy.visible(user, get_agents_in_group(DB_PATH, group_name))
        if not agent_ids:
            return APIResponse(success=False, message="No containers in group", error="empty_group")

        request = BulkOperationRequest(container_names=agent_ids, operation=operation)
        return await bulk_agent_operation(operation, request, root=True, user=user)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed group bulk operation: {e}")
        return APIResponse(success=False, message="Failed group bulk operation", error=str(e))


@router.post("/groups/{group_name}/logs/upload", response_model=APIResponse)
async def upload_logs_to_group(group_name: str, log_upload: LogUploadRequest,
                               user: dict | None = Depends(current_user)):
    """Upload log content to all containers in a group."""
    try:
        if not group_exists(DB_PATH, group_name):
            raise HTTPException(status_code=404, detail="Group not found")
        agent_ids = tenancy.visible(user, get_agents_in_group(DB_PATH, group_name))
        if not agent_ids:
            return APIResponse(success=False, message="No containers in group", error="empty_group")

        results = []
        existing = set(lxc.list_containers())
        for agent_id in agent_ids:
            if agent_id not in existing:
                results.append({"agent_id": agent_id, "success": False, "error": "Not found"})
                continue
            result = await perform_log_upload(agent_id, log_upload)
            results.append({"agent_id": agent_id, "success": result.get("success"), "error": result.get("stderr")})

        log_activity("group_logs_uploaded", {"group": group_name, "count": len(agent_ids)})
        return APIResponse(success=True, message="Logs uploaded to group", data={"results": results})
    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(success=False, message="Failed to upload logs to group", error=str(e))


@router.post("/groups/{group_name}/logs/schedule", response_model=APIResponse)
async def schedule_logs_to_group(group_name: str, schedule: LogScheduleRequest,
                                 user: dict | None = Depends(current_user)):
    """Schedule periodic log uploads to all containers in a group."""
    try:
        if not group_exists(DB_PATH, group_name):
            raise HTTPException(status_code=404, detail="Group not found")
        agent_ids = tenancy.visible(user, get_agents_in_group(DB_PATH, group_name))
        if not agent_ids:
            return APIResponse(success=False, message="No containers in group", error="empty_group")

        schedules = []
        for agent_id in agent_ids:
            result = await schedule_log_upload(agent_id, schedule, user=user)
            if result.success and result.data:
                schedules.append(result.data)
        log_activity("group_log_schedule_started", {"group": group_name, "count": len(schedules)})
        return APIResponse(success=True, message="Log schedules created", data={"schedules": schedules})
    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(success=False, message="Failed to schedule logs to group", error=str(e))
