"""
Container group models.
"""

from pydantic import BaseModel, Field, field_validator

from app.models.common import validate_alphanumeric_name


class GroupCreateRequest(BaseModel):
    """Create a container group"""
    name: str = Field(..., min_length=1, max_length=50)
    description: str | None = Field(default=None, max_length=200)

    @field_validator("name")
    @classmethod
    def validate_group_name(cls, v):
        return validate_alphanumeric_name(v)


class GroupRenameRequest(BaseModel):
    """Rename a container group"""
    new_name: str = Field(..., min_length=1, max_length=50)
    description: str | None = Field(default=None, max_length=200)

    @field_validator("new_name")
    @classmethod
    def validate_new_group_name(cls, v):
        return validate_alphanumeric_name(v)


class GroupAgentRequest(BaseModel):
    """Assign or remove containers from a group"""
    agent_ids: list[str] = Field(..., min_length=1)
