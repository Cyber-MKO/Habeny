"""
Activity log models.
"""
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.models.common import utc_now


class ActivityLog(BaseModel):
    """Activity log entry"""
    log_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=utc_now)
    action: str
    status: str  # success, error, partial
    details: Dict[str, Any]
    user_id: Optional[str] = None
    source_ip: Optional[str] = None
    duration_ms: Optional[float] = None


class ActivityLogListResponse(BaseModel):
    """Response for activity log list endpoint"""
    logs: List[ActivityLog]
    total: int
    limit: int
    offset: int
    has_more: bool
