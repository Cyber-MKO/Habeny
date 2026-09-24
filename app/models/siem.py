"""
SIEM-specific agent info and stats models.
"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import SIEMType


class WazuhAgentInfo(BaseModel):
    """Wazuh-specific agent information"""
    agent_id: str
    agent_name: str
    manager_host: str
    version: str
    os: dict[str, str]
    status: str
    last_keep_alive: datetime | None = None
    group: str
    node_name: str | None = None


class OSSECAgentInfo(BaseModel):
    """OSSEC-specific agent information"""
    agent_id: str
    agent_name: str
    ip_address: str
    status: str
    last_keep_alive: datetime | None = None


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
    average_eps: float | None = None
    total_events_24h: int | None = None

    model_config = ConfigDict(
        use_enum_values=True,
    )
