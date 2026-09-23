"""
Agent deployment, status, info and selection models.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, root_validator, validator

from app.models.common import HOSTNAME_PATTERN, IP_PATTERN, validate_alphanumeric_name
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
    manager_profile_id: Optional[str] = Field(None, description="Manager profile ID (overrides siem_type/ip/version/auth_key/os_type/group/memory/cpu/template)")
    siem_type: SIEMType = Field(default=SIEMType.WAZUH, description="SIEM type to deploy")
    siem_ip: Optional[str] = Field(default=None, description="SIEM manager IP address or hostname (not required for siem_type=none)")
    siem_version: Optional[str] = Field(default="4.14.2", description="SIEM agent version")
    os_type: OSType = Field(default=OSType.UBUNTU_22_04, description="Operating system type")
    agent_group: str = Field(default="default", description="Container group/profile")
    agent_base_name: str = Field(default="container", min_length=1, max_length=30, description="Base name for containers")
    memory_limit: Optional[str] = Field(default="512MB", description="Memory limit per container")
    cpu_shares: Optional[int] = Field(default=1024, ge=2, le=10240, description="CPU shares per container")
    config_template_id: Optional[str] = Field(None, description="Optional configuration template ID")
    autostart: Optional[bool] = Field(default=True, description="Start containers after creation")
    parallel_mode: ParallelMode = Field(default=ParallelMode.MULTIPROCESSING, description="Deployment parallelism mode")
    auto_create_group: Optional[bool] = Field(default=True, description="Create container group if missing")
    siem_auth_key: Optional[str] = Field(default=None, description="Installer authentication key (required for UTMstack)")
    deployment_id: Optional[str] = Field(default=None, max_length=64, description="Client-chosen ID for polling /agents/deploy/progress/{id}")
    
    @validator('siem_ip', always=True)
    def validate_siem_ip(cls, v, values):
        siem_type = values.get('siem_type')
        if siem_type and siem_type != SIEMType.NONE and siem_type != "none":
            if not v:
                raise ValueError('siem_ip is required when deploying a SIEM agent')
            if not (IP_PATTERN.match(v) or HOSTNAME_PATTERN.match(v)):
                raise ValueError('siem_ip must be a valid IP address or hostname')
        return v
    
    @validator('siem_auth_key', always=True)
    def validate_siem_auth_key(cls, v, values):
        siem_type = values.get('siem_type')
        if siem_type in (SIEMType.UTMSTACK, "utmstack") and not v:
            raise ValueError('siem_auth_key is required for UTMstack deployments')
        if siem_type in (SIEMType.ELASTIC, "elastic") and not v:
            raise ValueError('siem_auth_key (enrollment token) is required for Elastic deployments')
        return v
    
    @validator('agent_base_name')
    def validate_base_name(cls, v):
        return validate_alphanumeric_name(v)
    
    @root_validator(skip_on_failure=True)
    def validate_naming(cls, values):
        """Validate that generated container names won't exceed limits"""
        base_name = values.get('agent_base_name', '')
        count = values.get('count', 1)
        
        # Calculate max name length with numbering (e.g., container-1000)
        max_suffix_len = len(str(count))
        max_name_len = len(base_name) + 1 + max(4, max_suffix_len)  # +1 for hyphen, min 4 digits
        
        if max_name_len > 50:
            raise ValueError(f'Generated container names will exceed 50 characters. Max base_name length: {50 - max(4, max_suffix_len) - 1}')
        
        return values
    
    class Config:
        use_enum_values = True
        schema_extra = {
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
        }


class AgentDeploymentResult(BaseModel):
    """Result of container deployment"""
    agent_name: str
    container_id: str
    agent_seq_id: Optional[int] = None
    success: bool
    siem_type: Optional[SIEMType] = None
    siem_ip: Optional[str] = None
    agent_group: Optional[str] = None
    os_type: Optional[OSType] = None
    ip_address: Optional[str] = None
    agent_installation: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    
    class Config:
        use_enum_values = True


class ContainerStatus(BaseModel):
    """Container status information"""
    name: str
    state: ContainerState
    ip_addresses: List[str] = Field(default_factory=list)
    init_pid: int = -1
    memory_usage: Optional[str] = None
    cpu_usage: Optional[str] = None
    uptime: Optional[float] = None
    
    class Config:
        use_enum_values = True


class SIEMConnectivity(BaseModel):
    """SIEM connectivity information"""
    status: SIEMConnectivityStatus
    last_check: datetime
    agent_status: Optional[str] = None
    reason: Optional[str] = None
    last_event_time: Optional[datetime] = None
    events_per_second: Optional[float] = None
    
    class Config:
        use_enum_values = True


class AgentInfo(BaseModel):
    """Comprehensive container information"""
    agent_id: str
    agent_name: str
    agent_seq_id: Optional[int] = None
    lifecycle_status: AgentLifecycleStatus
    state: ContainerState
    siem_type: Optional[SIEMType] = None
    siem_ip: Optional[str] = None
    siem_version: Optional[str] = None
    agent_group: Optional[str] = None
    os_type: Optional[OSType] = None
    init_pid: int = -1
    ip_addresses: List[str] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    stats: Optional[Dict[str, Any]] = None
    siem_connectivity: Optional[SIEMConnectivity] = None
    tags: List[str] = Field(default_factory=list)
    
    class Config:
        use_enum_values = True


class AgentStats(BaseModel):
    """Detailed container statistics"""
    agent_id: str
    timestamp: datetime
    cpu_percent: Optional[float] = None
    memory_used_mb: Optional[float] = None
    memory_limit_mb: Optional[float] = None
    memory_percent: Optional[float] = None
    disk_used_mb: Optional[float] = None
    network_rx_bytes: Optional[int] = None
    network_tx_bytes: Optional[int] = None
    process_count: Optional[int] = None
    uptime_seconds: Optional[float] = None
    events_generated: Optional[int] = None
    events_per_second: Optional[float] = None


class AgentListResponse(BaseModel):
    """Response for container list endpoint"""
    agents: List[AgentInfo]
    total: int
    limit: int
    offset: int
    has_more: bool
    filters_applied: Optional[Dict[str, Any]] = None


class AgentSelector(BaseModel):
    """Container selection criteria for simulations"""
    agent_ids: Optional[List[str]] = Field(None, description="Specific container IDs")
    siem_type: Optional[SIEMType] = Field(None, description="Filter by SIEM type")
    agent_group: Optional[str] = Field(None, description="Filter by container group")
    tags: Optional[List[str]] = Field(None, description="Filter by tags")
    count: Optional[int] = Field(None, ge=1, le=1000, description="Random subset count")
    status: Optional[AgentLifecycleStatus] = Field(None, description="Filter by lifecycle status")
    
    @root_validator(skip_on_failure=True)
    def validate_selector(cls, values):
        """Ensure at least one selection criterion is provided"""
        if not any([
            values.get('agent_ids'),
            values.get('siem_type'),
            values.get('agent_group'),
            values.get('tags'),
            values.get('count'),
            values.get('status')
        ]):
            raise ValueError('At least one selection criterion must be provided')
        return values
    
    class Config:
        use_enum_values = True
        schema_extra = {
            "example": {
                "siem_type": "wazuh",
                "agent_group": "production",
                "count": 50,
                "status": "running"
            }
        }
