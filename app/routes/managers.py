"""
SIEM manager profile CRUD.
"""
import uuid

from fastapi import APIRouter, HTTPException

from app.config import DB_PATH
from app.db import create_manager, delete_manager, get_manager, get_manager_by_name, list_managers, update_manager
from app.models import APIResponse, ManagerProfileCreate, ManagerProfileUpdate
from app.services.activity import log_activity

router = APIRouter()


@router.get("/managers", response_model=APIResponse)
async def list_manager_profiles():
    """List all manager profiles"""
    try:
        managers = list_managers(DB_PATH)
        return APIResponse(success=True, message=f"Retrieved {len(managers)} manager profiles", data={"managers": managers, "total": len(managers)})
    except Exception as e:
        return APIResponse(success=False, message="Failed to list managers", error=str(e))


@router.get("/managers/{manager_id}", response_model=APIResponse)
async def get_manager_profile(manager_id: str):
    """Get a single manager profile"""
    try:
        mgr = get_manager(DB_PATH, manager_id)
        if not mgr:
            raise HTTPException(status_code=404, detail="Manager profile not found")
        return APIResponse(success=True, message="Manager profile retrieved", data=mgr)
    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(success=False, message="Failed to get manager", error=str(e))


@router.post("/managers", response_model=APIResponse)
async def create_manager_profile(profile: ManagerProfileCreate):
    """Create a manager profile"""
    try:
        if get_manager_by_name(DB_PATH, profile.name):
            raise HTTPException(status_code=400, detail=f"Manager profile '{profile.name}' already exists")
        manager_id = str(uuid.uuid4())
        data = profile.dict()
        mgr = create_manager(DB_PATH, manager_id, data)
        log_activity("manager_created", {"manager_id": manager_id, "name": profile.name})
        return APIResponse(success=True, message="Manager profile created", data=mgr)
    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(success=False, message="Failed to create manager", error=str(e))


@router.put("/managers/{manager_id}", response_model=APIResponse)
async def update_manager_profile(manager_id: str, profile: ManagerProfileUpdate):
    """Update a manager profile"""
    try:
        data = {k: v for k, v in profile.dict().items() if v is not None}
        mgr = update_manager(DB_PATH, manager_id, data)
        if not mgr:
            raise HTTPException(status_code=404, detail="Manager profile not found")
        log_activity("manager_updated", {"manager_id": manager_id})
        return APIResponse(success=True, message="Manager profile updated", data=mgr)
    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(success=False, message="Failed to update manager", error=str(e))


@router.delete("/managers/{manager_id}", response_model=APIResponse)
async def delete_manager_profile(manager_id: str):
    """Delete a manager profile"""
    try:
        if not delete_manager(DB_PATH, manager_id):
            raise HTTPException(status_code=404, detail="Manager profile not found")
        log_activity("manager_deleted", {"manager_id": manager_id})
        return APIResponse(success=True, message="Manager profile deleted")
    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(success=False, message="Failed to delete manager", error=str(e))
