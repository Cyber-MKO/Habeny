"""
Syslog config profile CRUD and connectivity test.
"""
import socket
import uuid

from fastapi import APIRouter, HTTPException, Query

from app.config import DB_PATH
from app.db import (
    create_syslog_config,
    delete_syslog_config,
    get_syslog_config,
    list_syslog_configs,
    update_syslog_config,
)
from app.models import APIResponse, SyslogConfigCreate, SyslogConfigUpdate
from app.services.activity import log_activity

router = APIRouter()


@router.get("/syslog-configs", response_model=APIResponse)
async def list_syslog_config_profiles():
    """List all syslog config profiles"""
    try:
        configs = list_syslog_configs(DB_PATH)
        return APIResponse(success=True, message=f"Retrieved {len(configs)} syslog configs", data={"configs": configs, "total": len(configs)})
    except Exception as e:
        return APIResponse(success=False, message="Failed to list syslog configs", error=str(e))


@router.post("/syslog-configs", response_model=APIResponse)
async def create_syslog_config_profile(config: SyslogConfigCreate):
    """Create a syslog config profile"""
    try:
        config_id = str(uuid.uuid4())
        result = create_syslog_config(DB_PATH, config_id, config.model_dump())
        log_activity("syslog_config_created", {"config_id": config_id, "name": config.name})
        return APIResponse(success=True, message="Syslog config created", data=result)
    except Exception as e:
        return APIResponse(success=False, message="Failed to create syslog config", error=str(e))


@router.get("/syslog-configs/{config_id}", response_model=APIResponse)
async def get_syslog_config_profile(config_id: str):
    """Get a syslog config profile"""
    try:
        cfg = get_syslog_config(DB_PATH, config_id)
        if not cfg:
            raise HTTPException(status_code=404, detail="Syslog config not found")
        return APIResponse(success=True, message="Syslog config retrieved", data=cfg)
    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(success=False, message="Failed to get syslog config", error=str(e))


@router.put("/syslog-configs/{config_id}", response_model=APIResponse)
async def update_syslog_config_profile(config_id: str, config: SyslogConfigUpdate):
    """Update a syslog config profile"""
    try:
        data = {k: v for k, v in config.model_dump().items() if v is not None}
        result = update_syslog_config(DB_PATH, config_id, data)
        if not result:
            raise HTTPException(status_code=404, detail="Syslog config not found")
        log_activity("syslog_config_updated", {"config_id": config_id})
        return APIResponse(success=True, message="Syslog config updated", data=result)
    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(success=False, message="Failed to update syslog config", error=str(e))


@router.delete("/syslog-configs/{config_id}", response_model=APIResponse)
async def delete_syslog_config_profile(config_id: str):
    """Delete a syslog config profile"""
    try:
        if not delete_syslog_config(DB_PATH, config_id):
            raise HTTPException(status_code=404, detail="Syslog config not found")
        log_activity("syslog_config_deleted", {"config_id": config_id})
        return APIResponse(success=True, message="Syslog config deleted")
    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(success=False, message="Failed to delete syslog config", error=str(e))


@router.post("/syslog-configs/test-connectivity", response_model=APIResponse)
async def test_syslog_connectivity(target_ip: str = Query(...), target_port: int = Query(514), protocol: str = Query("tcp")):
    """Test TCP/UDP connectivity to a syslog target"""
    try:
        if protocol.lower() == "tcp":
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((target_ip, target_port))
            sock.close()
            status = "connected"
        else:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(5)
            sock.sendto(b"<14>test connectivity check\n", (target_ip, target_port))
            sock.close()
            status = "sent"  # UDP is fire-and-forget

        return APIResponse(success=True, message=f"Connectivity test: {status}", data={
            "target_ip": target_ip, "target_port": target_port, "protocol": protocol, "status": status
        })
    except TimeoutError:
        return APIResponse(success=False, message="Connection timed out", data={
            "target_ip": target_ip, "target_port": target_port, "protocol": protocol, "status": "timeout"
        })
    except Exception as e:
        return APIResponse(success=False, message=f"Connection failed: {e}", data={
            "target_ip": target_ip, "target_port": target_port, "protocol": protocol, "status": "error", "error": str(e)
        })
