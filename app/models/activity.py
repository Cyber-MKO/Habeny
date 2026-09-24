"""
Activity log models.
"""
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.common import utc_now


class ActivityLog(BaseModel):
    """Activity log entry"""
    log_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=utc_now)
    action: str
    status: str  # success, error, partial
    details: dict[str, Any]
    user_id: str | None = None
    source_ip: str | None = None
    duration_ms: float | None = None


class ActivityLogListResponse(BaseModel):
    """Response for activity log list endpoint"""
    logs: list[ActivityLog]
    total: int
    limit: int
    offset: int
    has_more: bool
