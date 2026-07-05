import re
import uuid

from pydantic import BaseModel, Field, validator, root_validator
from typing import Optional, List, Dict, Any, Union
from enum import Enum
from datetime import datetime, timezone

_IP_PATTERN = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")
_HOSTNAME_PATTERN = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?)*$")
_ALPHANUM_START_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")
_CONTAINER_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")


def _validate_absolute_path(v: str) -> str:
    if not v.startswith('/'):
        raise ValueError('Path must be absolute (start with /)')
    if '..' in v:
        raise ValueError('Path cannot contain ..')
    return v


def _validate_alphanumeric_name(v: str) -> str:
    if not _ALPHANUM_START_PATTERN.match(v):
        raise ValueError("Name must start with alphanumeric and contain only alphanumeric, underscore, or hyphen")
    return v

# ===== ENUMS =====

class ContainerState(str, Enum):
    """LXC container states"""
    STOPPED = "STOPPED"
    RUNNING = "RUNNING"
    FROZEN = "FROZEN"
    STARTING = "STARTING"
    STOPPING = "STOPPING"
    ABORTING = "ABORTING"

class SIEMType(str, Enum):
    """Supported SIEM types"""
    NONE = "none"
    WAZUH = "wazuh"
    OSSEC = "ossec"
    OSSIM = "ossim"
    UTMSTACK = "utmstack"
    ELASTIC = "elastic"

class OSType(str, Enum):
    """Supported operating system types"""
    UBUNTU_22_04 = "ubuntu_22_04"
    UBUNTU_20_04 = "ubuntu_20_04"
    DEBIAN_11 = "debian_11"
    DEBIAN_10 = "debian_10"
    CENTOS_8 = "centos_8"

class ArchType(str, Enum):
    """Supported architectures"""
    AMD64 = "amd64"
    ARM64 = "arm64"
    ARMHF = "armhf"
    I386 = "i386"

class TemplateType(str, Enum):
    """LXC template types"""
    DOWNLOAD = "download"
    UBUNTU = "ubuntu"
    DEBIAN = "debian"
    ALPINE = "alpine"
    BUSYBOX = "busybox"

class ParallelMode(str, Enum):
    """Parallel execution modes"""
    SEQUENTIAL = "sequential"
    THREADING = "threading"
    MULTIPROCESSING = "multiprocessing"

class SyslogProtocol(str, Enum):
    """Syslog transport protocols"""
    UDP = "udp"
    TCP = "tcp"

class AgentLifecycleStatus(str, Enum):
    """Container lifecycle status"""
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"
    STARTING = "starting"
    STOPPING = "stopping"

class SIEMConnectivityStatus(str, Enum):
    """SIEM connectivity status"""
    CONNECTED = "connected"
    PENDING = "pending"
    DISCONNECTED = "disconnected"
    ERROR = "error"
    NEVER_CONNECTED = "never_connected"

class SimulationStatus(str, Enum):
    """Simulation status"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"

class SimulationProfile(str, Enum):
    """Attack simulation profiles"""
    AUTH_BRUTEFORCE = "auth_bruteforce"
    WEB_ATTACKS = "web_attacks"
    MALWARE_BEACON = "malware_beacon"
    LATERAL_MOVEMENT = "lateral_movement"
    DATA_EXFILTRATION = "data_exfiltration"
    PRIVILEGE_ESCALATION = "privilege_escalation"
    PORT_SCAN = "port_scan"
    SQL_INJECTION = "sql_injection"
    XSS_ATTACK = "xss_attack"
    DDoS_ATTACK = "ddos_attack"

class LogType(str, Enum):
    """Log types for injection"""
    AUTH = "auth"
    WEB = "web"
    APPLICATION = "application"
    SYSTEM = "system"
    SECURITY = "security"
    CUSTOM = "custom"

# ===== AGENT DEPLOYMENT MODELS =====

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
    
    @validator('siem_ip', always=True)
    def validate_siem_ip(cls, v, values):
        siem_type = values.get('siem_type')
        if siem_type and siem_type != SIEMType.NONE and siem_type != "none":
            if not v:
                raise ValueError('siem_ip is required when deploying a SIEM agent')
            if not (_IP_PATTERN.match(v) or _HOSTNAME_PATTERN.match(v)):
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
        return _validate_alphanumeric_name(v)
    
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

# ===== AGENT STATUS AND INFO MODELS =====

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

# ===== SIMULATION MODELS =====

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

class SimulationStartRequest(BaseModel):
    """Request to start an attack simulation"""
    profile_id: SimulationProfile = Field(..., description="Simulation profile to run")
    agent_selector: AgentSelector = Field(..., description="Containers to target")
    duration: int = Field(default=300, ge=1, le=86400, description="Duration in seconds")
    eps_target: int = Field(default=100, ge=1, le=10000, description="Target events per second")
    intensity: Optional[str] = Field(default="medium", description="Intensity level (low, medium, high)")
    burst_mode: Optional[bool] = Field(default=False, description="Generate events in bursts")
    custom_parameters: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Profile-specific parameters")
    
    class Config:
        use_enum_values = True
        schema_extra = {
            "example": {
                "profile_id": "auth_bruteforce",
                "agent_selector": {
                    "siem_type": "wazuh",
                    "count": 50
                },
                "duration": 600,
                "eps_target": 200,
                "intensity": "high",
                "burst_mode": True
            }
        }


class CustomLogSimulationRequest(BaseModel):
    """Request to load a custom EPS log simulation"""
    agent_selector: AgentSelector = Field(..., description="Containers to target")
    file_path: str = Field(default="/var/log/custom-eps.json", description="Destination log file path")
    message: str = Field(default="Custom EPS log event", max_length=500, description="Log message")
    src_ip: str = Field(default="192.168.1.100", description="Source IP address")
    dest_ip: str = Field(default="10.0.0.1", description="Destination IP address")
    duration: int = Field(default=300, ge=1, le=86400, description="Duration in seconds")
    eps: int = Field(default=100, ge=1, le=10000, description="Events per second")
    seq_start: int = Field(default=1, ge=1, description="Starting sequence number")
    start_time: Optional[datetime] = Field(default=None, description="Optional ISO start time")
    extra_fields: Dict[str, Any] = Field(default_factory=dict, description="Extra JSON fields to include")

    @validator('file_path')
    def validate_file_path(cls, v):
        return _validate_absolute_path(v)

    class Config:
        schema_extra = {
            "example": {
                "agent_selector": {"agent_group": "load-test", "count": 10},
                "file_path": "/var/log/custom-eps.json",
                "message": "Custom EPS log event",
                "src_ip": "192.168.1.100",
                "dest_ip": "10.0.0.1",
                "duration": 300,
                "eps": 200,
                "seq_start": 1,
                "extra_fields": {"severity": "info", "app": "simulator"}
            }
        }

class SimulationInfo(BaseModel):
    """Simulation information"""
    simulation_id: str
    profile_id: SimulationProfile
    status: SimulationStatus
    target_agents: List[str]
    duration: int
    eps_target: int
    intensity: Optional[str] = None
    burst_mode: bool = False
    started_at: datetime
    completed_at: Optional[datetime] = None
    stopped_at: Optional[datetime] = None
    events_generated: int = 0
    events_per_second_actual: Optional[float] = None
    error: Optional[str] = None
    custom_parameters: Optional[Dict[str, Any]] = None
    
    class Config:
        use_enum_values = True

class SimulationStopRequest(BaseModel):
    """Request to stop a simulation"""
    simulation_id: str
    reason: Optional[str] = Field(None, description="Reason for stopping")

class SimulationListResponse(BaseModel):
    """Response for simulation list endpoint"""
    simulations: List[SimulationInfo]
    total: int
    running: int
    completed: int
    failed: int
    available_profiles: List[str]


class SyslogDeviceType(str, Enum):
    """Network device types for syslog simulation"""
    ROUTER = "router"
    SWITCH = "switch"
    FIREWALL = "firewall"
    IDS = "ids"
    MIXED = "mixed"


class SyslogSimulationRequest(BaseModel):
    """Request to start a syslog simulation"""
    target_ip: str = Field(..., description="SIEM manager IP/hostname")
    target_port: int = Field(default=514, ge=1, le=65535, description="Syslog port")
    protocol: SyslogProtocol = Field(default=SyslogProtocol.TCP, description="Syslog transport protocol")
    eps: int = Field(default=100, ge=1, le=10000, description="Events per second")
    duration: int = Field(default=300, ge=1, le=86400, description="Duration in seconds")
    device_count: int = Field(default=4, ge=1, le=1000, description="Number of simulated devices")
    device_type: SyslogDeviceType = Field(default=SyslogDeviceType.MIXED, description="Device type or mixed")
    device_name_prefix: str = Field(default="device", max_length=50, description="Device name prefix")
    facility: int = Field(default=1, ge=0, le=23, description="Syslog facility")

    class Config:
        schema_extra = {
            "example": {
                "target_ip": "172.17.0.1",
                "target_port": 514,
                "protocol": "tcp",
                "eps": 200,
                "duration": 300,
                "device_count": 4,
                "device_type": "mixed",
                "device_name_prefix": "edge",
                "facility": 1
            }
        }

# ===== MANAGER PROFILE MODELS =====

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

    class Config:
        use_enum_values = True


# ===== SYSLOG CONFIG MODELS =====

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


# ===== CONFIGURATION MODELS =====

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

class LogUploadRequest(BaseModel):
    """Request to upload log content to a container"""
    content: str = Field(..., description="Log content to upload")
    destination_path: str = Field(..., description="Destination path in container")
    log_type: LogType = Field(default=LogType.CUSTOM, description="Type of log")
    append: bool = Field(default=False, description="Append to existing file or overwrite")
    
    @validator('destination_path')
    def validate_path(cls, v):
        return _validate_absolute_path(v)
    
    class Config:
        use_enum_values = True
        schema_extra = {
            "example": {
                "content": "Jan 27 10:15:32 server sshd[1234]: Failed password for admin from 192.168.1.100",
                "destination_path": "/var/log/auth.log",
                "log_type": "auth",
                "append": True
            }
        }

class LogScheduleRequest(BaseModel):
    """Schedule log uploads to a container"""
    content: str = Field(..., description="Log content to upload")
    destination_path: str = Field(..., description="Destination path in container")
    log_type: LogType = Field(default=LogType.CUSTOM, description="Type of log")
    append: bool = Field(default=True, description="Append to existing file or overwrite")
    interval_seconds: int = Field(default=120, ge=5, le=86400, description="Interval between uploads")
    duration_seconds: Optional[int] = Field(default=None, ge=10, le=604800, description="Duration to run the schedule")
    indefinite: bool = Field(default=False, description="Run indefinitely")

    @validator('destination_path')
    def validate_path(cls, v):
        return _validate_absolute_path(v)


class GroupCreateRequest(BaseModel):
    """Create a container group"""
    name: str = Field(..., min_length=1, max_length=50)
    description: Optional[str] = Field(default=None, max_length=200)

    @validator("name")
    def validate_group_name(cls, v):
        return _validate_alphanumeric_name(v)


class GroupRenameRequest(BaseModel):
    """Rename a container group"""
    new_name: str = Field(..., min_length=1, max_length=50)
    description: Optional[str] = Field(default=None, max_length=200)

    @validator("new_name")
    def validate_new_group_name(cls, v):
        return _validate_alphanumeric_name(v)


class GroupAgentRequest(BaseModel):
    """Assign or remove containers from a group"""
    agent_ids: List[str] = Field(..., min_items=1)

class LogBundleUploadRequest(BaseModel):
    """Request to upload a bundle of log files"""
    log_files: List[Dict[str, str]] = Field(..., description="List of {path: content} mappings")
    agent_selector: AgentSelector = Field(..., description="Containers to receive logs")
    distribution_strategy: str = Field(default="round_robin", description="How to distribute logs (round_robin, random, all)")
    
    class Config:
        schema_extra = {
            "example": {
                "log_files": [
                    {"path": "/var/log/auth.log", "content": "..."},
                    {"path": "/var/log/apache2/access.log", "content": "..."}
                ],
                "agent_selector": {"count": 10},
                "distribution_strategy": "round_robin"
            }
        }

# ===== REPORTING MODELS =====

class ReportGenerateRequest(BaseModel):
    """Request to generate a report"""
    start_time: datetime = Field(..., description="Report start time")
    end_time: datetime = Field(..., description="Report end time")
    siem_ids: Optional[List[str]] = Field(None, description="Filter by SIEM IDs")
    scenario_ids: Optional[List[str]] = Field(None, description="Filter by simulation IDs")
    metrics: List[str] = Field(default_factory=lambda: ["all"], description="Metrics to include")
    include_findings: bool = Field(default=True, description="Include automated findings")
    format: str = Field(default="json", description="Report format (json, pdf, csv)")
    
    @validator('end_time')
    def validate_time_range(cls, v, values):
        """Validate time range"""
        start_time = values.get('start_time')
        if start_time and v <= start_time:
            raise ValueError('end_time must be after start_time')
        return v
    
    class Config:
        schema_extra = {
            "example": {
                "start_time": "2025-01-01T00:00:00Z",
                "end_time": "2025-01-27T23:59:59Z",
                "metrics": ["eps", "connectivity", "resource_usage"],
                "include_findings": True,
                "format": "json"
            }
        }

class ReportSummary(BaseModel):
    """Report summary section"""
    total_agents: int
    agents_by_siem: Dict[str, int]
    agents_by_os: Dict[str, int]
    total_simulations: int
    simulations_in_range: List[str]
    time_range: Dict[str, str]
    simulations_by_type: Optional[Dict[str, int]] = None
    syslog_targets: Optional[Dict[str, int]] = None

class ReportMetrics(BaseModel):
    """Report metrics section"""
    eps_distribution: Optional[Dict[str, Any]] = None
    connectivity_stats: Optional[Dict[str, Any]] = None
    resource_usage: Optional[Dict[str, Any]] = None
    agent_stability: Optional[Dict[str, Any]] = None
    performance_benchmarks: Optional[Dict[str, Any]] = None

class ReportFinding(BaseModel):
    """Individual report finding"""
    finding_id: str
    severity: str  # info, warning, critical
    title: str
    description: str
    recommendation: Optional[str] = None
    affected_agents: Optional[List[str]] = None
    metrics: Optional[Dict[str, Any]] = None

class Report(BaseModel):
    """Complete report"""
    report_id: str
    generated_at: datetime
    time_range: Dict[str, str]
    summary: ReportSummary
    metrics: ReportMetrics
    findings: List[ReportFinding] = Field(default_factory=list)
    metadata: Optional[Dict[str, Any]] = None

class ReportListResponse(BaseModel):
    """Response for report list endpoint"""
    reports: List[Dict[str, Any]]
    total: int
    
# ===== ACTIVITY LOG MODELS =====

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

class ActivityLog(BaseModel):
    """Activity log entry"""
    log_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=utc_now)
    action: str
    status: str  # success, error, partial
    details: Dict[str, Any]
    user_id: Optional[str] = None
    source_ip: Optional[str] = None
    duration_ms: Optional[float] = None

class ActivityLogListResponse(BaseModel):
    """Response for activity log list endpoint"""
    logs: List[ActivityLog]
    total: int
    limit: int
    offset: int
    has_more: bool

# ===== BULK OPERATIONS =====

class BulkOperationRequest(BaseModel):
    """Bulk operation request"""
    container_names: List[str] = Field(..., min_items=1, description="List of container names")
    operation: str = Field(..., description="Operation to perform (start, stop, restart, delete)")
    force: bool = Field(default=False, description="Force operation")
    parallel: bool = Field(default=True, description="Execute in parallel")
    max_workers: Optional[int] = Field(default=None, ge=1, le=32, description="Max parallel workers")
    
    @validator('operation')
    def validate_operation(cls, v):
        """Validate operation type"""
        allowed_operations = ['start', 'stop', 'restart', 'delete', 'freeze', 'unfreeze']
        if v.lower() not in allowed_operations:
            raise ValueError(f'Operation must be one of: {", ".join(allowed_operations)}')
        return v.lower()
    
    class Config:
        schema_extra = {
            "example": {
                "container_names": ["container-0001", "container-0002", "container-0003"],
                "operation": "restart",
                "parallel": True,
                "max_workers": 10
            }
        }

class BulkOperationResult(BaseModel):
    """Result of bulk operation"""
    total_requested: int
    successful: int
    failed: int
    results: List[Dict[str, Any]]
    elapsed_time_seconds: Optional[float] = None

# ===== API RESPONSE MODELS =====

class APIResponse(BaseModel):
    """Standard API response"""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    timestamp: datetime = Field(default_factory=utc_now)
    
    class Config:
        schema_extra = {
            "example": {
                "success": True,
                "message": "Operation completed successfully",
                "data": {"container_name": "container-01", "state": "running"},
                "error": None,
                "timestamp": "2025-01-27T10:00:00Z"
            }
        }

class ErrorResponse(BaseModel):
    """Error response"""
    success: bool = False
    error: str
    error_code: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    timestamp: datetime = Field(default_factory=utc_now)

class HealthCheckResponse(BaseModel):
    """Health check response"""
    status: str
    version: str
    uptime_seconds: float
    containers_count: int
    system_info: Dict[str, Any]
    timestamp: datetime = Field(default_factory=utc_now)

# ===== SIEM-SPECIFIC MODELS =====

class WazuhAgentInfo(BaseModel):
    """Wazuh-specific agent information"""
    agent_id: str
    agent_name: str
    manager_host: str
    version: str
    os: Dict[str, str]
    status: str
    last_keep_alive: Optional[datetime] = None
    group: str
    node_name: Optional[str] = None

class OSSECAgentInfo(BaseModel):
    """OSSEC-specific agent information"""
    agent_id: str
    agent_name: str
    ip_address: str
    status: str
    last_keep_alive: Optional[datetime] = None

class OSSIMAgentInfo(BaseModel):
    """OSSIM-specific agent information"""
    agent_id: str
    sensor_id: str
    ip_address: str
    status: str
    version: str

class SIEMStats(BaseModel):
    """SIEM-specific statistics"""
    siem_type: SIEMType
    total_agents: int
    connected_agents: int
    disconnected_agents: int
    connection_rate: float
    average_eps: Optional[float] = None
    total_events_24h: Optional[int] = None
    
    class Config:
        use_enum_values = True

# ===== CONTAINER OPERATIONS (LEGACY COMPATIBILITY) =====

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
        if not _CONTAINER_NAME_PATTERN.match(v):
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

# ===== ADVANCED FEATURES =====

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

class PerformanceMetrics(BaseModel):
    """Performance metrics"""
    operation: str
    containers_processed: int
    elapsed_time_seconds: float
    containers_per_second: float
    success_rate: float
    parallel_workers: int
    timestamp: datetime = Field(default_factory=utc_now)

class SystemStats(BaseModel):
    """System statistics"""
    cpu_count: int
    total_memory_mb: int
    available_memory_mb: int
    disk_total_gb: float
    disk_used_gb: float
    disk_available_gb: float
    load_average: List[float]
    containers_running: int
    containers_stopped: int
    containers_total: int
    active_simulations: int

# ===== SNAPSHOT AND BACKUP =====

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
