"""
Legacy container operations, advanced features and snapshot/backup models.
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, validator

from app.models.common import CONTAINER_NAME_PATTERN
from app.models.enums import ParallelMode


class ContainerCreate(BaseModel):
    """Basic container creation request"""
    name: str = Field(..., min_length=1, max_length=50, description="Container name")
    template: str = Field(default="download", description="LXC template to use")
    distro: str = Field(default="ubuntu", description="Linux distribution")
    release: str = Field(default="jammy", description="Distribution release")
    arch: str = Field(default="amd64", description="Architecture")
    memory_limit: Optional[str] = Field(default="512MB", description="Memory limit (e.g., 512MB, 2GB)")
    cpu_shares: Optional[int] = Field(default=1024, ge=2, le=10240, description="CPU shares (2-10240)")
    network_config: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Custom network configuration")
    autostart: Optional[bool] = Field(default=False, description="Start container automatically on boot")
    
    @validator('name')
    def validate_name(cls, v):
        if not CONTAINER_NAME_PATTERN.match(v):
            raise ValueError('Container name must start with alphanumeric and contain only alphanumeric, underscore, dot, or hyphen')
        return v


class ContainerCreateWithWazuh(ContainerCreate):
    """Container creation with Wazuh agent installation (legacy)"""
    install_wazuh: bool = Field(default=False, description="Install Wazuh agent")
    wazuh_manager: Optional[str] = Field(default="172.17.0.1", description="Wazuh manager IP/hostname")
    agent_group: Optional[str] = Field(default="default", description="Wazuh agent group")
    wazuh_version: Optional[str] = Field(default="4.14.2", description="Wazuh version to install")


class BatchContainerCreate(BaseModel):
    """Batch container creation (legacy compatibility)"""
    base_name: str = Field(..., min_length=1, max_length=40)
    count: int = Field(default=1, ge=1, le=100)
    template: str = Field(default="download")
    distro: str = Field(default="ubuntu")
    release: str = Field(default="jammy")
    arch: str = Field(default="amd64")
    memory_limit: Optional[str] = Field(default="512MB")
    cpu_shares: Optional[int] = Field(default=1024, ge=2, le=10240)
    install_wazuh: bool = Field(default=False)
    wazuh_manager: Optional[str] = Field(default="172.17.0.1")
    agent_group: Optional[str] = Field(default="default")
    wazuh_version: Optional[str] = Field(default="4.14.2")
    start_delay: Optional[int] = Field(default=5, ge=1, le=60)
    parallel_mode: Optional[ParallelMode] = Field(default=ParallelMode.MULTIPROCESSING)
    
    class Config:
        use_enum_values = True


class ScalingPolicy(BaseModel):
    """Auto-scaling policy for containers"""
    policy_id: str
    min_agents: int = Field(ge=0)
    max_agents: int = Field(ge=1)
    target_metric: str  # cpu_usage, memory_usage, eps
    target_value: float
    scale_up_threshold: float
    scale_down_threshold: float
    cooldown_seconds: int = Field(default=300, ge=60)
    enabled: bool = True


class AlertRule(BaseModel):
    """Alert rule for monitoring"""
    rule_id: str
    name: str
    condition: str  # expression to evaluate
    threshold: float
    severity: str  # info, warning, critical
    notification_channels: List[str]
    enabled: bool = True


class NetworkTopology(BaseModel):
    """Network topology definition"""
    topology_id: str
    name: str
    subnets: List[Dict[str, Any]]
    routing_rules: List[Dict[str, Any]]
    firewall_rules: List[Dict[str, Any]]


class SnapshotCreate(BaseModel):
    """Snapshot creation request"""
    snapshot_name: str = Field(..., min_length=1, max_length=50)
    comment: Optional[str] = Field(None, max_length=200)
    include_memory: bool = Field(default=False)


class BackupRequest(BaseModel):
    """Backup request for containers"""
    agent_ids: List[str]
    backup_name: str
    compression: bool = Field(default=True)
    include_logs: bool = Field(default=False)


class RestoreRequest(BaseModel):
    """Restore request"""
    backup_id: str
    target_name: Optional[str] = None
    start_after_restore: bool = Field(default=False)
