"""
SIEM manager profile and syslog config profile models.
"""
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.common import INSTALL_FIELD_CHECKS
from app.models.enums import OSType, SIEMType, SyslogProtocol


class ManagerProfileCreate(BaseModel):
    """Create a manager profile with deployment defaults"""
    name: str = Field(..., min_length=1, max_length=100, description="Profile name (unique)")
    description: Optional[str] = Field(None, max_length=500)
    siem_type: SIEMType = Field(..., description="SIEM type")
    siem_ip: Optional[str] = Field(None, description="Manager IP or hostname")
    siem_version: Optional[str] = Field(None, description="SIEM agent version")
    siem_auth_key: Optional[str] = Field(None, description="Auth key (UTMstack)")
    os_type: OSType = Field(default=OSType.UBUNTU_22_04)
    agent_group: str = Field(default="default")
    memory_limit: Optional[str] = Field(default="512MB")
    cpu_shares: Optional[int] = Field(default=1024, ge=2, le=10240)
    config_template_id: Optional[str] = Field(None)


    @field_validator('siem_ip', 'siem_version', 'siem_auth_key', 'agent_group')
    @classmethod
    def validate_install_fields(cls, v, info):
        """These values end up in agent install scripts and host paths."""
        return INSTALL_FIELD_CHECKS[info.field_name](v)

    class Config:
        use_enum_values = True


class ManagerProfileUpdate(BaseModel):
    """Update a manager profile (all fields optional)"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    siem_type: Optional[SIEMType] = None
    siem_ip: Optional[str] = None
    siem_version: Optional[str] = None
    siem_auth_key: Optional[str] = None
    os_type: Optional[OSType] = None
    agent_group: Optional[str] = None
    memory_limit: Optional[str] = None
    cpu_shares: Optional[int] = Field(None, ge=2, le=10240)
    config_template_id: Optional[str] = None


    @field_validator('siem_ip', 'siem_version', 'siem_auth_key', 'agent_group')
    @classmethod
    def validate_install_fields(cls, v, info):
        """These values end up in agent install scripts and host paths."""
        return INSTALL_FIELD_CHECKS[info.field_name](v)

    class Config:
        use_enum_values = True


class SyslogConfigCreate(BaseModel):
    """Create a syslog forwarding profile"""
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    manager_profile_id: Optional[str] = Field(None, description="Link to a manager profile")
    target_ip: str = Field(..., description="Syslog target IP/hostname")
    target_port: int = Field(default=514, ge=1, le=65535)
    protocol: SyslogProtocol = Field(default=SyslogProtocol.TCP)
    siem_type: Optional[SIEMType] = Field(None, description="SIEM type for context-aware behavior")

    class Config:
        use_enum_values = True


class SyslogConfigUpdate(BaseModel):
    """Update a syslog config (all fields optional)"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    manager_profile_id: Optional[str] = None
    target_ip: Optional[str] = None
    target_port: Optional[int] = Field(None, ge=1, le=65535)
    protocol: Optional[SyslogProtocol] = None
    siem_type: Optional[SIEMType] = None

    class Config:
        use_enum_values = True
