"""
Bulk operations, API responses, health check, error and performance models.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, validator

from app.models.common import utc_now


class BulkOperationRequest(BaseModel):
    """Bulk operation request"""
    container_names: List[str] = Field(..., min_items=1, description="List of container names")
    operation: str = Field(..., description="Operation to perform (start, stop, restart, delete)")
    force: bool = Field(default=False, description="Force operation")
    parallel: bool = Field(default=True, description="Execute in parallel")
    max_workers: Optional[int] = Field(default=None, ge=1, le=32, description="Max parallel workers")
    
    @validator('operation')
    def validate_operation(cls, v):
        """Validate operation type"""
        allowed_operations = ['start', 'stop', 'restart', 'delete', 'freeze', 'unfreeze']
        if v.lower() not in allowed_operations:
            raise ValueError(f'Operation must be one of: {", ".join(allowed_operations)}')
        return v.lower()
    
    class Config:
        schema_extra = {
            "example": {
                "container_names": ["container-0001", "container-0002", "container-0003"],
                "operation": "restart",
                "parallel": True,
                "max_workers": 10
            }
        }


class BulkOperationResult(BaseModel):
    """Result of bulk operation"""
    total_requested: int
    successful: int
    failed: int
    results: List[Dict[str, Any]]
    elapsed_time_seconds: Optional[float] = None


class APIResponse(BaseModel):
    """Standard API response"""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    timestamp: datetime = Field(default_factory=utc_now)
    
    class Config:
        schema_extra = {
            "example": {
                "success": True,
                "message": "Operation completed successfully",
                "data": {"container_name": "container-01", "state": "running"},
                "error": None,
                "timestamp": "2025-01-27T10:00:00Z"
            }
        }


class ErrorResponse(BaseModel):
    """Error response"""
    success: bool = False
    error: str
    error_code: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    timestamp: datetime = Field(default_factory=utc_now)


class HealthCheckResponse(BaseModel):
    """Health check response"""
    status: str
    version: str
    uptime_seconds: float
    containers_count: int
    system_info: Dict[str, Any]
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
    load_average: List[float]
    containers_running: int
    containers_stopped: int
    containers_total: int
    active_simulations: int
