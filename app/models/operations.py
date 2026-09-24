"""
Bulk operations, API responses, health check, error and performance models.
"""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.common import utc_now


class BulkOperationRequest(BaseModel):
    """Bulk operation request"""
    container_names: list[str] = Field(..., min_length=1, description="List of container names")
    operation: str = Field(..., description="Operation to perform (start, stop, restart, delete)")
    force: bool = Field(default=False, description="Force operation")
    parallel: bool = Field(default=True, description="Execute in parallel")
    max_workers: int | None = Field(default=None, ge=1, le=32, description="Max parallel workers")

    @field_validator('operation')
    @classmethod
    def validate_operation(cls, v):
        """Validate operation type"""
        allowed_operations = ['start', 'stop', 'restart', 'delete', 'freeze', 'unfreeze']
        if v.lower() not in allowed_operations:
            raise ValueError(f'Operation must be one of: {", ".join(allowed_operations)}')
        return v.lower()

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "container_names": ["container-0001", "container-0002", "container-0003"],
                "operation": "restart",
                "parallel": True,
                "max_workers": 10
            }
        },
    )


class BulkOperationResult(BaseModel):
    """Result of bulk operation"""
    total_requested: int
    successful: int
    failed: int
    results: list[dict[str, Any]]
    elapsed_time_seconds: float | None = None


class APIResponse(BaseModel):
    """Standard API response"""
    success: bool
    message: str
    data: dict[str, Any] | None = None
    error: str | None = None
    timestamp: datetime = Field(default_factory=utc_now)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": True,
                "message": "Operation completed successfully",
                "data": {"container_name": "container-01", "state": "running"},
                "error": None,
                "timestamp": "2025-01-27T10:00:00Z"
            }
        },
    )


class ErrorResponse(BaseModel):
    """Error response"""
    success: bool = False
    error: str
    error_code: str | None = None
    details: dict[str, Any] | None = None
    timestamp: datetime = Field(default_factory=utc_now)


class HealthCheckResponse(BaseModel):
    """Health check response"""
    status: str
    version: str
    uptime_seconds: float
    containers_count: int
    system_info: dict[str, Any]
    timestamp: datetime = Field(default_factory=utc_now)


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
    load_average: list[float]
    containers_running: int
    containers_stopped: int
    containers_total: int
    active_simulations: int
