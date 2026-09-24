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
    operation: str = Field(..., description="Operation to perform (start, stop, delete)")

    @field_validator('operation')
    @classmethod
    def validate_operation(cls, v):
        """Validate operation type"""
        allowed_operations = ['start', 'stop', 'delete']
        if v.lower() not in allowed_operations:
            raise ValueError(f'Operation must be one of: {", ".join(allowed_operations)}')
        return v.lower()

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "container_names": ["container-0001", "container-0002", "container-0003"],
                "operation": "stop"
            }
        },
    )


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


class HealthCheckResponse(BaseModel):
    """Health check response"""
    status: str
    version: str
    uptime_seconds: float
    containers_count: int
    system_info: dict[str, Any]
    timestamp: datetime = Field(default_factory=utc_now)
