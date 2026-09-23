"""
Benchmark run and comparison request models.
"""
from typing import List, Optional

from pydantic import BaseModel


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


class BenchmarkCompareRequest(BaseModel):
    benchmark_ids: List[str]
