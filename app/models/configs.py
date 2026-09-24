"""
Configuration template import/export models.
"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import SIEMType


class ConfigImportRequest(BaseModel):
    """Request to import a configuration template"""
    name: str = Field(..., min_length=1, max_length=100, description="Template name")
    siem_type: SIEMType = Field(..., description="SIEM type this config is for")
    content: str = Field(..., description="Configuration file content")
    description: str | None = Field(None, max_length=500, description="Template description")
    version: str | None = Field(None, description="Config version")
    tags: list[str] = Field(default_factory=list, description="Tags for categorization")

    model_config = ConfigDict(
        use_enum_values=True,
        json_schema_extra={
            "example": {
                "name": "High Security Wazuh Config",
                "siem_type": "wazuh",
                "content": "<ossec_config>...</ossec_config>",
                "description": "Enhanced security configuration for production environments",
                "version": "1.0",
                "tags": ["production", "high-security"]
            }
        },
    )


class ConfigTemplate(BaseModel):
    """Configuration template"""
    template_id: str
    name: str
    siem_type: SIEMType
    content: str
    description: str | None = None
    version: str | None = None
    tags: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime | None = None
    usage_count: int = 0

    model_config = ConfigDict(
        use_enum_values=True,
    )
