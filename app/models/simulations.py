"""
Simulation request/response/info models.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, validator

from app.models.agents import AgentSelector
from app.models.common import validate_absolute_path
from app.models.enums import SimulationProfile, SimulationStatus, SyslogDeviceType, SyslogProtocol


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
        return validate_absolute_path(v)

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
