"""
SIEM manager profile (SIEM target) models: agent deployment defaults, the syslog port
simulations send to, and the search API detection checks ask.
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.common import INSTALL_FIELD_CHECKS
from app.models.enums import OSType, SIEMType, SyslogProtocol


class ManagerProfileCreate(BaseModel):
    """Create a manager profile with deployment defaults"""
    name: str = Field(..., min_length=1, max_length=100, description="Profile name (unique)")
    description: str | None = Field(None, max_length=500)
    siem_type: SIEMType = Field(..., description="SIEM type")
    siem_ip: str | None = Field(None, description="Manager IP or hostname")
    siem_version: str | None = Field(None, description="SIEM agent version")
    siem_auth_key: str | None = Field(None, description="Auth key (UTMstack)")
    os_type: OSType = Field(default=OSType.UBUNTU_22_04)
    agent_group: str = Field(default="default")
    memory_limit: str | None = Field(default="512MB")
    cpu_shares: int | None = Field(default=1024, ge=2, le=10240)
    config_template_id: str | None = Field(None)
    detection_url: str | None = Field(None, max_length=300, description="SIEM search API for checking detections (admins)")
    detection_username: str | None = Field(None, max_length=200)
    detection_secret: str | None = Field(None, max_length=2000, description="Password, or an Elasticsearch API key")
    detection_fingerprint: str | None = Field(None, pattern=r"^([0-9A-F]{2}:){31}[0-9A-F]{2}$")
    syslog_port: int | None = Field(None, ge=1, le=65535, description="Port the SIEM receives syslog on, at siem_ip")
    syslog_protocol: SyslogProtocol | None = Field(None, description="tcp (default) or udp")

    @field_validator('siem_ip', 'siem_version', 'siem_auth_key', 'agent_group')
    @classmethod
    def validate_install_fields(cls, v, info):
        """These values end up in agent install scripts and host paths."""
        return INSTALL_FIELD_CHECKS[info.field_name](v)

    model_config = ConfigDict(
        use_enum_values=True,
    )


class ManagerProfileUpdate(BaseModel):
    """Update a manager profile (all fields optional)"""
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = None
    siem_type: SIEMType | None = None
    siem_ip: str | None = None
    siem_version: str | None = None
    siem_auth_key: str | None = None
    os_type: OSType | None = None
    agent_group: str | None = None
    memory_limit: str | None = None
    cpu_shares: int | None = Field(None, ge=2, le=10240)
    config_template_id: str | None = None
    detection_url: str | None = Field(None, max_length=300)
    detection_username: str | None = Field(None, max_length=200)
    detection_secret: str | None = Field(None, max_length=2000)
    detection_fingerprint: str | None = Field(None, pattern=r"^(([0-9A-F]{2}:){31}[0-9A-F]{2})?$")
    syslog_port: int | None = Field(None, ge=1, le=65535)
    syslog_protocol: SyslogProtocol | None = None

    @field_validator('siem_ip', 'siem_version', 'siem_auth_key', 'agent_group')
    @classmethod
    def validate_install_fields(cls, v, info):
        """These values end up in agent install scripts and host paths."""
        return INSTALL_FIELD_CHECKS[info.field_name](v)

    model_config = ConfigDict(
        use_enum_values=True,
    )
