"""
Log upload and log schedule models.
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.common import validate_absolute_path


class LogUploadRequest(BaseModel):
    """Request to upload log content to a container"""
    content: str = Field(..., description="Log content to upload")
    destination_path: str = Field(..., description="Destination path in container")
    append: bool = Field(default=False, description="Append to existing file or overwrite")

    @field_validator('destination_path')
    @classmethod
    def validate_path(cls, v):
        return validate_absolute_path(v)

    model_config = ConfigDict(
        use_enum_values=True,
        json_schema_extra={
            "example": {
                "content": "Jan 27 10:15:32 server sshd[1234]: Failed password for admin from 192.168.1.100",
                "destination_path": "/var/log/auth.log",
                "append": True
            }
        },
    )


class LogScheduleRequest(BaseModel):
    """Schedule log uploads to a container"""
    content: str = Field(..., description="Log content to upload")
    destination_path: str = Field(..., description="Destination path in container")
    append: bool = Field(default=True, description="Append to existing file or overwrite")
    interval_seconds: int = Field(default=120, ge=5, le=86400, description="Interval between uploads")
    duration_seconds: int | None = Field(default=None, ge=10, le=604800, description="Duration to run the schedule")
    indefinite: bool = Field(default=False, description="Run indefinitely")

    @field_validator('destination_path')
    @classmethod
    def validate_path(cls, v):
        return validate_absolute_path(v)
