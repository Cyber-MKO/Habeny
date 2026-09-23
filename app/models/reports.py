"""
Report generation and report content models.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, validator


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
