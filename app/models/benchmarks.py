"""
Benchmark run and comparison request models.
"""

from pydantic import BaseModel, field_validator

from app.core.os_images import OS_IMAGES
from app.core.validation import validate_group
from app.models.common import INSTALL_FIELD_CHECKS


class BenchmarkStartRequest(BaseModel):
    scenario_id: str = "linear_scale"
    name: str | None = None
    siem_type: str | None = "none"
    siem_ip: str | None = None
    siem_version: str | None = None
    siem_auth_key: str | None = None
    base_name: str | None = None
    memory_limit: str | None = "256MB"
    os_type: str | None = "ubuntu_22_04"
    agent_group: str | None = "benchmark"
    metric_interval: int | None = None
    failure_threshold: float | None = None
    manager_profile_id: str | None = None  # fills unset SIEM fields (incl. the stored auth key) server-side

    @field_validator('base_name')
    @classmethod
    def validate_base_name(cls, v):
        """Becomes part of container names, i.e. paths under /var/lib/lxc."""
        return v if v in (None, "") else validate_group(v)

    @field_validator('os_type')
    @classmethod
    def validate_os_type(cls, v):
        if v not in (None, "") and v not in OS_IMAGES:
            raise ValueError(f"must be one of: {', '.join(OS_IMAGES)}")
        return v

    @field_validator('siem_ip', 'siem_version', 'siem_auth_key', 'agent_group')
    @classmethod
    def validate_install_fields(cls, v, info):
        """These values end up in agent install scripts and host paths."""
        return INSTALL_FIELD_CHECKS[info.field_name](v)


class BenchmarkCompareRequest(BaseModel):
    benchmark_ids: list[str]
