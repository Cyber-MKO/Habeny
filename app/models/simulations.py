"""
Simulation request/response/info models.
"""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.agents import AgentSelector
from app.models.common import validate_absolute_path
from app.models.enums import SimulationProfile, SimulationStatus, SyslogDeviceType, SyslogProtocol


class SimulationStartRequest(BaseModel):
    """Request to start an attack simulation"""
    profile_id: SimulationProfile = Field(..., description="Simulation profile to run")
    agent_selector: AgentSelector = Field(..., description="Containers to target")
    duration: int = Field(default=300, ge=1, le=86400, description="Duration in seconds")
    eps_target: int = Field(default=100, ge=1, le=10000, description="Events per second written in each container")
    detection_profile_id: str | None = Field(None, description="Manager profile whose SIEM to ask, after the run, "
                                               "what it detected (needs its detection API set)")

    model_config = ConfigDict(
        use_enum_values=True,
        json_schema_extra={
            "example": {
                "profile_id": "auth_bruteforce",
                "agent_selector": {
                    "siem_type": "wazuh",
                    "count": 50
                },
                "duration": 600,
                "eps_target": 200
            }
        },
    )


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
    start_time: datetime | None = Field(default=None, description="Optional ISO start time")
    extra_fields: dict[str, Any] = Field(default_factory=dict, description="Extra JSON fields to include")

    @field_validator('file_path')
    @classmethod
    def validate_file_path(cls, v):
        return validate_absolute_path(v)

    model_config = ConfigDict(
        json_schema_extra={
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
        },
    )


class SimulationInfo(BaseModel):
    """Simulation information"""
    simulation_id: str
    profile_id: SimulationProfile
    status: SimulationStatus
    target_agents: list[str]
    duration: int
    eps_target: int
    intensity: str | None = None
    burst_mode: bool = False
    started_at: datetime
    completed_at: datetime | None = None
    stopped_at: datetime | None = None
    events_generated: int = 0
    events_per_second_actual: float | None = None
    error: str | None = None
    custom_parameters: dict[str, Any] | None = None

    model_config = ConfigDict(
        use_enum_values=True,
    )


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

    model_config = ConfigDict(
        json_schema_extra={
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
        },
    )
