"""
Configuration template import/export models.
"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from app.models.enums import SIEMType


class ConfigImportRequest(BaseModel):
    """Request to import a configuration template"""
    name: str = Field(..., min_length=1, max_length=100, description="Template name")
    siem_type: SIEMType = Field(..., description="SIEM type this config is for")
    content: str = Field(..., description="Configuration file content")
    description: Optional[str] = Field(None, max_length=500, description="Template description")
    version: Optional[str] = Field(None, description="Config version")
    tags: List[str] = Field(default_factory=list, description="Tags for categorization")
    
    class Config:
        use_enum_values = True
        schema_extra = {
            "example": {
                "name": "High Security Wazuh Config",
                "siem_type": "wazuh",
                "content": "<ossec_config>...</ossec_config>",
                "description": "Enhanced security configuration for production environments",
                "version": "1.0",
                "tags": ["production", "high-security"]
            }
        }


class ConfigTemplate(BaseModel):
    """Configuration template"""
    template_id: str
    name: str
    siem_type: SIEMType
    content: str
    description: Optional[str] = None
    version: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: Optional[datetime] = None
    usage_count: int = 0
    
    class Config:
        use_enum_values = True


class ConfigExportResponse(BaseModel):
    """Response for config export"""
    template: ConfigTemplate
    download_url: Optional[str] = None
