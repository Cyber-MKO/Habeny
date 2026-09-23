"""
Configuration template import/export.
"""
import json
import uuid

from fastapi import APIRouter, HTTPException

from app.config import CONFIGS_DIR
from app.services.activity import log_activity
from app.state import config_templates
from models import APIResponse, ConfigImportRequest, utc_now

router = APIRouter()


@router.get("/configs", response_model=APIResponse)
async def list_configs():
    """List all configuration templates"""
    try:
        return APIResponse(
            success=True,
            message="Configuration templates retrieved",
            data={
                "templates": list(config_templates.values()),
                "total": len(config_templates)
            }
        )
    except Exception as e:
        return APIResponse(success=False, message="Failed to list configs", error=str(e))


@router.post("/configs/import", response_model=APIResponse)
async def import_config(config: ConfigImportRequest):
    """Import a configuration template"""
    try:
        template_id = str(uuid.uuid4())

        template = {
            "template_id": template_id,
            "name": config.name,
            "siem_type": config.siem_type,
            "content": config.content,
            "description": config.description,
            "created_at": utc_now().isoformat()
        }

        config_templates[template_id] = template

        # Save to file
        config_file = CONFIGS_DIR / f"{template_id}.json"
        with open(config_file, 'w') as f:
            json.dump(template, f, indent=2)

        log_activity("config_imported", {"template_id": template_id, "name": config.name})

        return APIResponse(
            success=True,
            message="Configuration template imported",
            data=template
        )

    except Exception as e:
        return APIResponse(success=False, message="Failed to import config", error=str(e))


@router.get("/configs/export/{template_id}", response_model=APIResponse)
async def export_config(template_id: str):
    """Export a configuration template"""
    try:
        if template_id not in config_templates:
            raise HTTPException(status_code=404, detail=f"Template {template_id} not found")

        template = config_templates[template_id]

        return APIResponse(
            success=True,
            message="Configuration template retrieved",
            data=template
        )

    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(success=False, message="Failed to export config", error=str(e))
