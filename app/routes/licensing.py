"""
This server's license: status for every signed-in user, installing one for admins.
"""
import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.models import APIResponse
from app.services import licensing
from app.services.activity import log_activity
from app.services.auth import require_admin, require_user

router = APIRouter()


class LicenseRequest(BaseModel):
    license: str = Field(..., min_length=10, max_length=20000)


@router.get("/license", response_model=APIResponse, dependencies=[Depends(require_user)])
async def get_license():
    info = await asyncio.to_thread(licensing.status_info)
    return APIResponse(success=True, message=info["message"], data=info)


@router.post("/license", response_model=APIResponse, dependencies=[Depends(require_admin)])
async def install_license(body: LicenseRequest):
    try:
        payload = await asyncio.to_thread(licensing.install, body.license)
    except licensing.LicenseError as e:
        log_activity("license_install_failed", {"error": str(e)}, status="error")
        raise HTTPException(status_code=400, detail=str(e)) from None
    log_activity("license_installed", {"license": payload["id"], "customer": payload["customer"],
                                       "expires": payload.get("expires"),
                                       "max_containers": payload.get("max_containers")})
    await asyncio.to_thread(licensing.check_alert)
    info = await asyncio.to_thread(licensing.status_info)
    return APIResponse(success=True, message=f"License {payload['id']} installed. {info['message']}", data=info)

