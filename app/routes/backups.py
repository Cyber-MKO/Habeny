"""
Full backups (admins only): list, take one now, download. Restoring is done with
`habeny backup restore` while Habeny is stopped (it replaces the running database).
"""
import asyncio

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse

from app.models import APIResponse
from app.services import backup
from app.services.activity import log_activity
from app.services.auth import require_admin

router = APIRouter(prefix="/system/backups", dependencies=[Depends(require_admin)])


@router.get("", response_model=APIResponse)
async def list_backups():
    items = await asyncio.to_thread(backup.list_backups)
    return APIResponse(success=True, message=f"{len(items)} backups",
                       data={"backups": items, "schedule": backup.schedule_status()})


@router.post("", response_model=APIResponse)
async def create_backup():
    try:
        path = await asyncio.to_thread(backup.create_backup, "manual")
    except backup.BackupError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    log_activity("backup_created", {"backup": path.name})
    item = next(b for b in backup.list_backups() if b["name"] == path.name)
    return APIResponse(success=True, message=f"Backup {path.name} created", data={"backup": item})


@router.get("/{name}")
async def download_backup(name: str):
    try:
        path = backup.backup_path(name)
    except backup.BackupError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    log_activity("backup_downloaded", {"backup": name})
    return FileResponse(path, media_type="application/gzip", filename=name)
