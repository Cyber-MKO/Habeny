"""
Benchmark run and comparison request models.
"""
from typing import List, Optional

from pydantic import BaseModel, field_validator

from app.core.validation import validate_group
from app.models.common import INSTALL_FIELD_CHECKS


class BenchmarkStartRequest(BaseModel):
    scenario_id: str = "linear_scale"
    name: Optional[str] = None
    siem_type: Optional[str] = "none"
    siem_ip: Optional[str] = None
    siem_version: Optional[str] = None
    siem_auth_key: Optional[str] = None
    base_name: Optional[str] = None
    memory_limit: Optional[str] = "256MB"
    os_type: Optional[str] = "ubuntu_22_04"
    agent_group: Optional[str] = "benchmark"
    metric_interval: Optional[int] = None
    failure_threshold: Optional[float] = None
    manager_profile_id: Optional[str] = None  # fills unset SIEM fields (incl. the stored auth key) server-side

    @field_validator('base_name')
    @classmethod
    def validate_base_name(cls, v):
        """Becomes part of container names, i.e. paths under /var/lib/lxc."""
        return v if v in (None, "") else validate_group(v)

    @field_validator('siem_ip', 'siem_version', 'siem_auth_key', 'agent_group')
    @classmethod
    def validate_install_fields(cls, v, info):
        """These values end up in agent install scripts and host paths."""
        return INSTALL_FIELD_CHECKS[info.field_name](v)


class BenchmarkCompareRequest(BaseModel):
    benchmark_ids: List[str]
