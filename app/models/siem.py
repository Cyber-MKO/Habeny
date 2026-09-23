"""
SIEM-specific agent info and stats models.
"""
from datetime import datetime
from typing import Dict, Optional

from pydantic import BaseModel

from app.models.enums import SIEMType


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
