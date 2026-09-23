"""
Log upload and log schedule models.
"""
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, validator

from app.models.agents import AgentSelector
from app.models.common import validate_absolute_path
from app.models.enums import LogType


class LogUploadRequest(BaseModel):
    """Request to upload log content to a container"""
    content: str = Field(..., description="Log content to upload")
    destination_path: str = Field(..., description="Destination path in container")
    log_type: LogType = Field(default=LogType.CUSTOM, description="Type of log")
    append: bool = Field(default=False, description="Append to existing file or overwrite")
    
    @validator('destination_path')
    def validate_path(cls, v):
        return validate_absolute_path(v)
    
    class Config:
        use_enum_values = True
        schema_extra = {
            "example": {
                "content": "Jan 27 10:15:32 server sshd[1234]: Failed password for admin from 192.168.1.100",
                "destination_path": "/var/log/auth.log",
                "log_type": "auth",
                "append": True
            }
        }


class LogScheduleRequest(BaseModel):
    """Schedule log uploads to a container"""
    content: str = Field(..., description="Log content to upload")
    destination_path: str = Field(..., description="Destination path in container")
    log_type: LogType = Field(default=LogType.CUSTOM, description="Type of log")
    append: bool = Field(default=True, description="Append to existing file or overwrite")
    interval_seconds: int = Field(default=120, ge=5, le=86400, description="Interval between uploads")
    duration_seconds: Optional[int] = Field(default=None, ge=10, le=604800, description="Duration to run the schedule")
    indefinite: bool = Field(default=False, description="Run indefinitely")

    @validator('destination_path')
    def validate_path(cls, v):
        return validate_absolute_path(v)


class LogBundleUploadRequest(BaseModel):
    """Request to upload a bundle of log files"""
    log_files: List[Dict[str, str]] = Field(..., description="List of {path: content} mappings")
    agent_selector: AgentSelector = Field(..., description="Containers to receive logs")
    distribution_strategy: str = Field(default="round_robin", description="How to distribute logs (round_robin, random, all)")
    
    class Config:
        schema_extra = {
            "example": {
                "log_files": [
                    {"path": "/var/log/auth.log", "content": "..."},
                    {"path": "/var/log/apache2/access.log", "content": "..."}
                ],
                "agent_selector": {"count": 10},
                "distribution_strategy": "round_robin"
            }
        }
