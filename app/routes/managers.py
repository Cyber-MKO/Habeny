"""
SIEM manager profile CRUD, and the detection API connection used to check what the SIEM
detected (setting it is for admins: it makes this server connect to a URL with credentials).
"""
import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from app.config import DB_PATH
from app.core.secrets import secret_hint
from app.db import create_manager, delete_manager, get_manager, get_manager_by_name, list_managers, update_manager
from app.models import APIResponse, ManagerProfileCreate, ManagerProfileUpdate
from app.services import detection
from app.services.activity import log_activity
from app.services.auth import current_user

router = APIRouter()


DETECTION_FIELDS = ("detection_url", "detection_username", "detection_secret", "detection_fingerprint")


def public_manager(mgr: dict) -> dict:
    """Profile as returned by the API: secrets are replaced by presence flags and hints."""
    key, secret = mgr.get("siem_auth_key"), mgr.get("detection_secret")
    out = {k: v for k, v in mgr.items() if k not in ("siem_auth_key", "detection_secret")}
    out["has_siem_auth_key"] = bool(key)
    out["siem_auth_key_hint"] = secret_hint(key)
    out["has_detection_secret"] = bool(secret)
    out["detection_configured"] = detection.configured(mgr)
    return out


def _check_detection_fields(data: dict, user: dict | None) -> dict:
    """Detection settings: admins only, and a well-formed URL."""
    given = {k: v for k, v in data.items() if k in DETECTION_FIELDS and v is not None}
    if not given:
        return data
    if user is not None and not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Only admins can set a profile's detection API connection")
    if given.get("detection_url"):
        try:
            data["detection_url"] = detection.normalize_url(given["detection_url"])
        except detection.DetectionError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None
    return data


@router.get("/managers", response_model=APIResponse)
async def list_manager_profiles():
    """List all manager profiles"""
    try:
        managers = list_managers(DB_PATH)
        return APIResponse(success=True, message=f"Retrieved {len(managers)} manager profiles", data={"managers": [public_manager(m) for m in managers], "total": len(managers)})
    except Exception as e:
        return APIResponse(success=False, message="Failed to list managers", error=str(e))


@router.get("/managers/{manager_id}", response_model=APIResponse)
async def get_manager_profile(manager_id: str):
    """Get a single manager profile"""
    try:
        mgr = get_manager(DB_PATH, manager_id)
        if not mgr:
            raise HTTPException(status_code=404, detail="Manager profile not found")
        return APIResponse(success=True, message="Manager profile retrieved", data=public_manager(mgr))
    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(success=False, message="Failed to get manager", error=str(e))


@router.post("/managers", response_model=APIResponse)
async def create_manager_profile(profile: ManagerProfileCreate, user: dict | None = Depends(current_user)):
    """Create a manager profile"""
    try:
        if get_manager_by_name(DB_PATH, profile.name):
            raise HTTPException(status_code=400, detail=f"Manager profile '{profile.name}' already exists")
        manager_id = str(uuid.uuid4())
        data = _check_detection_fields(profile.model_dump(), user)
        mgr = create_manager(DB_PATH, manager_id, data)
        log_activity("manager_created", {"manager_id": manager_id, "name": profile.name})
        return APIResponse(success=True, message="Manager profile created", data=public_manager(mgr))
    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(success=False, message="Failed to create manager", error=str(e))


@router.put("/managers/{manager_id}", response_model=APIResponse)
async def update_manager_profile(manager_id: str, profile: ManagerProfileUpdate,
                                 user: dict | None = Depends(current_user)):
    """Update a manager profile. An empty detection_url or detection_fingerprint clears it."""
    try:
        data = _check_detection_fields({k: v for k, v in profile.model_dump().items() if v is not None}, user)
        mgr = update_manager(DB_PATH, manager_id, data)
        if not mgr:
            raise HTTPException(status_code=404, detail="Manager profile not found")
        log_activity("manager_updated", {"manager_id": manager_id,
                                         "fields": sorted(k for k in data if k != "detection_secret")
                                         + (["detection_secret"] if "detection_secret" in data else [])})
        return APIResponse(success=True, message="Manager profile updated", data=public_manager(mgr))
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


@router.post("/managers/{manager_id}/detection/test", response_model=APIResponse)
async def test_detection_connection(manager_id: str):
    """Check the profile's detection API: reachable, credentials accepted, alerts in the last 24 hours.
    A self-signed certificate answers 409 with its fingerprint, for an admin to confirm."""
    mgr = get_manager(DB_PATH, manager_id)
    if not mgr:
        raise HTTPException(status_code=404, detail="Manager profile not found")
    if not detection.configured(mgr):
        raise HTTPException(status_code=400, detail="Set a detection URL first (Wazuh and Elastic profiles only)")
    try:
        result = await asyncio.to_thread(detection.test_connection, mgr)
    except detection.FingerprintNeeded as e:
        return JSONResponse(status_code=409, content={"detail": str(e), "fingerprint": e.fingerprint})
    except detection.DetectionError as e:
        raise HTTPException(status_code=502, detail=str(e)) from None
    return APIResponse(success=True, message=f"Connected: {result['alerts_last_24h']} alerts in the last 24 hours",
                       data=result)
