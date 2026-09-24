"""
Per-container log upload and recurring log upload schedules.
"""
import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.core.lxc_backend import lxc
from app.models import APIResponse, LogScheduleRequest, LogUploadRequest, utc_now
from app.services import tenancy
from app.services.activity import log_activity
from app.services.auth import current_user
from app.services.logs import perform_log_upload, run_log_schedule, schedule_public
from app.state import scheduled_log_tasks

router = APIRouter()


@router.post("/agents/{agent_id}/logs/schedule", response_model=APIResponse)
async def schedule_log_upload(agent_id: str, schedule: LogScheduleRequest,
                              user: dict | None = Depends(current_user)):
    """Schedule periodic log uploads to a container."""
    try:
        if agent_id not in lxc.list_containers() or not tenancy.can_see(user, agent_id):
            raise HTTPException(status_code=404, detail=f"Container {agent_id} not found")

        if schedule.interval_seconds < 5:
            raise HTTPException(status_code=400, detail="interval_seconds must be at least 5 seconds")

        if not schedule.indefinite and not schedule.duration_seconds:
            raise HTTPException(status_code=400, detail="duration_seconds is required unless indefinite is true")

        schedule_id = str(uuid.uuid4())
        log_upload = LogUploadRequest(
            content=schedule.content,
            destination_path=schedule.destination_path,
            log_type=schedule.log_type,
            append=schedule.append
        )

        scheduled_log_tasks[schedule_id] = {
            "schedule_id": schedule_id,
            "agent_id": agent_id,
            "interval_seconds": schedule.interval_seconds,
            "duration_seconds": schedule.duration_seconds,
            "indefinite": schedule.indefinite,
            "status": "starting",
            "created_at": utc_now().isoformat(),
            # kept so the schedule can resume after a restart (not shown in the API)
            "request": log_upload.model_dump(),
        }

        task = asyncio.create_task(
            run_log_schedule(
                schedule_id,
                agent_id,
                log_upload,
                schedule.interval_seconds,
                schedule.duration_seconds,
                schedule.indefinite
            )
        )
        scheduled_log_tasks[schedule_id]["task"] = task
        log_activity("log_schedule_started", {"schedule_id": schedule_id, "container_id": agent_id})

        return APIResponse(
            success=True,
            message="Log schedule created",
            data=schedule_public(scheduled_log_tasks[schedule_id])
        )
    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(success=False, message="Failed to schedule log upload", error=str(e))


@router.post("/agents/logs/schedules/{schedule_id}/stop", response_model=APIResponse)
async def stop_log_schedule(schedule_id: str, user: dict | None = Depends(current_user)):
    """Stop a scheduled log upload."""
    try:
        schedule = scheduled_log_tasks.get(schedule_id)
        if not schedule or not tenancy.can_see(user, schedule.get("agent_id", "")):
            raise HTTPException(status_code=404, detail="Schedule not found")
        task = schedule.get("task")
        if task and not task.done():
            task.cancel()
        schedule["status"] = "stopped"
        log_activity("log_schedule_stopped", {"schedule_id": schedule_id, "container_id": schedule.get("agent_id")})
        return APIResponse(success=True, message="Schedule stopped", data=schedule_public(schedule))
    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(success=False, message="Failed to stop schedule", error=str(e))


@router.get("/agents/logs/schedules", response_model=APIResponse)
async def list_log_schedules(user: dict | None = Depends(current_user)):
    """List the log upload schedules for containers you can see."""
    schedules = list(scheduled_log_tasks.values())
    allowed = set(tenancy.visible(user, [s.get("agent_id", "") for s in schedules]))
    data = [schedule_public(s) for s in schedules if s.get("agent_id", "") in allowed]
    return APIResponse(success=True, message="Log schedules retrieved", data={"schedules": data})


@router.post("/agents/{agent_id}/logs/upload", response_model=APIResponse)
async def upload_logs_to_agent(agent_id: str, log_upload: LogUploadRequest,
                               user: dict | None = Depends(current_user)):
    """Upload log content to a container"""
    try:
        if agent_id not in lxc.list_containers() or not tenancy.can_see(user, agent_id):
            raise HTTPException(status_code=404, detail=f"Container {agent_id} not found")

        # Write log content to container
        result = await perform_log_upload(agent_id, log_upload)

        if result["success"]:
            log_activity("logs_uploaded", {
                "agent_id": agent_id,
                "path": log_upload.destination_path
            })

            return APIResponse(
                success=True,
                message=f"Logs uploaded to {log_upload.destination_path}",
                data={
                    "agent_id": agent_id,
                    "destination_path": log_upload.destination_path,
                    "bytes_written": len(log_upload.content)
                }
            )
        else:
            return APIResponse(
                success=False,
                message="Failed to upload logs",
                error=result.get("stderr")
            )

    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(success=False, message="Failed to upload logs", error=str(e))
