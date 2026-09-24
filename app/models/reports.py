"""
Report generation and report content models.
"""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator


class ReportGenerateRequest(BaseModel):
    """Request to generate a report"""
    start_time: datetime = Field(..., description="Report start time")
    end_time: datetime = Field(..., description="Report end time")
    siem_ids: list[str] | None = Field(None, description="Filter by SIEM IDs")
    scenario_ids: list[str] | None = Field(None, description="Filter by simulation IDs")
    metrics: list[str] = Field(default_factory=lambda: ["all"], description="Metrics to include")
    include_findings: bool = Field(default=True, description="Include automated findings")
    format: str = Field(default="json", description="Report format (json, pdf, csv)")

    @field_validator('end_time')
    @classmethod
    def validate_time_range(cls, v, info: ValidationInfo):
        """Validate time range"""
        start_time = info.data.get('start_time')
        if start_time and v <= start_time:
            raise ValueError('end_time must be after start_time')
        return v

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "start_time": "2025-01-01T00:00:00Z",
                "end_time": "2025-01-27T23:59:59Z",
                "metrics": ["eps", "connectivity", "resource_usage"],
                "include_findings": True,
                "format": "json"
            }
        },
    )


class ReportSummary(BaseModel):
    """Report summary section"""
    total_agents: int
    agents_by_siem: dict[str, int]
    agents_by_os: dict[str, int]
    total_simulations: int
    simulations_in_range: list[str]
    time_range: dict[str, str]
    simulations_by_type: dict[str, int] | None = None
    syslog_targets: dict[str, int] | None = None


class ReportMetrics(BaseModel):
    """Report metrics section"""
    eps_distribution: dict[str, Any] | None = None
    connectivity_stats: dict[str, Any] | None = None
    resource_usage: dict[str, Any] | None = None
    agent_stability: dict[str, Any] | None = None
    performance_benchmarks: dict[str, Any] | None = None


class ReportFinding(BaseModel):
    """Individual report finding"""
    finding_id: str
    severity: str  # info, warning, critical
    title: str
    description: str
    recommendation: str | None = None
    affected_agents: list[str] | None = None
    metrics: dict[str, Any] | None = None


class Report(BaseModel):
    """Complete report"""
    report_id: str
    generated_at: datetime
    time_range: dict[str, str]
    summary: ReportSummary
    metrics: ReportMetrics
    findings: list[ReportFinding] = Field(default_factory=list)
    metadata: dict[str, Any] | None = None


class ReportListResponse(BaseModel):
    """Response for report list endpoint"""
    reports: list[dict[str, Any]]
    total: int
