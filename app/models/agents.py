"""
Agent deployment, status, info and selection models.
"""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from app.models.common import INSTALL_FIELD_CHECKS, validate_alphanumeric_name
from app.models.enums import (
    AgentLifecycleStatus,
    ContainerState,
    OSType,
    ParallelMode,
    SIEMConnectivityStatus,
    SIEMType,
)


class AgentDeploymentRequest(BaseModel):
    """Request to deploy containers with SIEM agents"""
    count: int = Field(..., ge=1, le=1000, description="Number of containers to deploy")
    manager_profile_id: str | None = Field(None, description="Manager profile ID (overrides siem_type/ip/version/auth_key/os_type/group/memory/cpu/template)")
    siem_type: SIEMType = Field(default=SIEMType.WAZUH, description="SIEM type to deploy")
    siem_ip: str | None = Field(default=None, validate_default=True,
                                   description="SIEM manager IP address or hostname (not required for siem_type=none)")
    siem_version: str | None = Field(default="4.14.2", description="SIEM agent version")
    os_type: OSType = Field(default=OSType.UBUNTU_22_04, description="Operating system type")
    agent_group: str = Field(default="default", description="Container group/profile")
    agent_base_name: str = Field(default="container", min_length=1, max_length=30, description="Base name for containers")
    memory_limit: str | None = Field(default="512MB", description="Memory limit per container")
    cpu_shares: int | None = Field(default=1024, ge=2, le=10240, description="CPU shares per container")
    config_template_id: str | None = Field(None, description="Optional configuration template ID")
    autostart: bool | None = Field(default=True, description="Start containers after creation")
    parallel_mode: ParallelMode = Field(default=ParallelMode.MULTIPROCESSING, description="Deployment parallelism mode")
    auto_create_group: bool | None = Field(default=True, description="Create container group if missing")
    siem_auth_key: str | None = Field(default=None, validate_default=True,
                                         description="Installer authentication key (required for UTMstack)")
    deployment_id: str | None = Field(default=None, max_length=64, description="Client-chosen ID for polling /agents/deploy/progress/{id}")

    @field_validator('siem_ip')
    @classmethod
    def validate_siem_ip(cls, v, info: ValidationInfo):
        values = info.data  # fields declared above this one
        siem_type = values.get('siem_type')
        # With a manager profile the server fills it in (checked again after that)
        if (siem_type and siem_type != SIEMType.NONE and siem_type != "none"
                and not values.get('manager_profile_id') and not v):
            raise ValueError('siem_ip is required when deploying a SIEM agent')
        return INSTALL_FIELD_CHECKS["siem_ip"](v)

    @field_validator('siem_auth_key')
    @classmethod
    def validate_siem_auth_key(cls, v, info: ValidationInfo):
        values = info.data
        siem_type = values.get('siem_type')
        if values.get('manager_profile_id'):
            return INSTALL_FIELD_CHECKS["siem_auth_key"](v)  # stored (encrypted) in the profile
        if siem_type in (SIEMType.UTMSTACK, "utmstack") and not v:
            raise ValueError('siem_auth_key is required for UTMstack deployments')
        if siem_type in (SIEMType.ELASTIC, "elastic") and not v:
            raise ValueError('siem_auth_key (enrollment token) is required for Elastic deployments')
        return INSTALL_FIELD_CHECKS["siem_auth_key"](v)

    @field_validator('siem_version', 'agent_group')
    @classmethod
    def validate_install_fields(cls, v, info):
        return INSTALL_FIELD_CHECKS[info.field_name](v)

    @field_validator('agent_base_name')
    @classmethod
    def validate_base_name(cls, v):
        return validate_alphanumeric_name(v)

    @model_validator(mode="after")
    def validate_naming(self):
        """Validate that generated container names won't exceed limits"""
        base_name = self.agent_base_name or ''
        count = self.count or 1

        # Calculate max name length with numbering (e.g., container-1000)
        max_suffix_len = len(str(count))
        max_name_len = len(base_name) + 1 + max(4, max_suffix_len)  # +1 for hyphen, min 4 digits

        if max_name_len > 50:
            raise ValueError(f'Generated container names will exceed 50 characters. Max base_name length: {50 - max(4, max_suffix_len) - 1}')

        return self

    model_config = ConfigDict(
        use_enum_values=True,
        json_schema_extra={
            "example": {
                "count": 100,
                "siem_type": "wazuh",
                "siem_ip": "192.168.1.100",
                "siem_version": "4.14.2",
                "os_type": "ubuntu_22_04",
                "agent_group": "production",
                "agent_base_name": "prod-container",
                "memory_limit": "1GB",
                "cpu_shares": 2048
            }
        },
    )


class AgentDeploymentResult(BaseModel):
    """Result of container deployment"""
    agent_name: str
    container_id: str
    agent_seq_id: int | None = None
    success: bool
    siem_type: SIEMType | None = None
    siem_ip: str | None = None
    agent_group: str | None = None
    os_type: OSType | None = None
    ip_address: str | None = None
    agent_installation: dict[str, Any] | None = None
    error: str | None = None

    model_config = ConfigDict(
        use_enum_values=True,
    )


class ContainerStatus(BaseModel):
    """Container status information"""
    name: str
    state: ContainerState
    ip_addresses: list[str] = Field(default_factory=list)
    init_pid: int = -1
    memory_usage: str | None = None
    cpu_usage: str | None = None
    uptime: float | None = None

    model_config = ConfigDict(
        use_enum_values=True,
    )


class SIEMConnectivity(BaseModel):
    """SIEM connectivity information"""
    status: SIEMConnectivityStatus
    last_check: datetime
    agent_status: str | None = None
    reason: str | None = None
    last_event_time: datetime | None = None
    events_per_second: float | None = None

    model_config = ConfigDict(
        use_enum_values=True,
    )


class AgentInfo(BaseModel):
    """Comprehensive container information"""
    agent_id: str
    agent_name: str
    agent_seq_id: int | None = None
    lifecycle_status: AgentLifecycleStatus
    state: ContainerState
    siem_type: SIEMType | None = None
    siem_ip: str | None = None
    siem_version: str | None = None
    agent_group: str | None = None
    os_type: OSType | None = None
    init_pid: int = -1
    ip_addresses: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    stats: dict[str, Any] | None = None
    siem_connectivity: SIEMConnectivity | None = None
    tags: list[str] = Field(default_factory=list)

    model_config = ConfigDict(
        use_enum_values=True,
    )


class AgentStats(BaseModel):
    """Detailed container statistics"""
    agent_id: str
    timestamp: datetime
    cpu_percent: float | None = None
    memory_used_mb: float | None = None
    memory_limit_mb: float | None = None
    memory_percent: float | None = None
    disk_used_mb: float | None = None
    network_rx_bytes: int | None = None
    network_tx_bytes: int | None = None
    process_count: int | None = None
    uptime_seconds: float | None = None
    events_generated: int | None = None
    events_per_second: float | None = None


class AgentListResponse(BaseModel):
    """Response for container list endpoint"""
    agents: list[AgentInfo]
    total: int
    limit: int
    offset: int
    has_more: bool
    filters_applied: dict[str, Any] | None = None


class AgentSelector(BaseModel):
    """Container selection criteria for simulations"""
    agent_ids: list[str] | None = Field(None, description="Specific container IDs")
    siem_type: SIEMType | None = Field(None, description="Filter by SIEM type")
    agent_group: str | None = Field(None, description="Filter by container group")
    tags: list[str] | None = Field(None, description="Filter by tags")
    count: int | None = Field(None, ge=1, le=1000, description="Random subset count")
    status: AgentLifecycleStatus | None = Field(None, description="Filter by lifecycle status")

    @model_validator(mode="after")
    def validate_selector(self):
        """Ensure at least one selection criterion is provided"""
        if not any([self.agent_ids, self.siem_type, self.agent_group, self.tags, self.count, self.status]):
            raise ValueError('At least one selection criterion must be provided')
        return self

    model_config = ConfigDict(
        use_enum_values=True,
        json_schema_extra={
            "example": {
                "siem_type": "wazuh",
                "agent_group": "production",
                "count": 50,
                "status": "running"
            }
        },
    )
