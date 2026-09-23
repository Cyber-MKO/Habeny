"""
Container group models.
"""
from typing import List, Optional

from pydantic import BaseModel, Field, validator

from app.models.common import validate_alphanumeric_name


class GroupCreateRequest(BaseModel):
    """Create a container group"""
    name: str = Field(..., min_length=1, max_length=50)
    description: Optional[str] = Field(default=None, max_length=200)

    @validator("name")
    def validate_group_name(cls, v):
        return validate_alphanumeric_name(v)


class GroupRenameRequest(BaseModel):
    """Rename a container group"""
    new_name: str = Field(..., min_length=1, max_length=50)
    description: Optional[str] = Field(default=None, max_length=200)

    @validator("new_name")
    def validate_new_group_name(cls, v):
        return validate_alphanumeric_name(v)


class GroupAgentRequest(BaseModel):
    """Assign or remove containers from a group"""
    agent_ids: List[str] = Field(..., min_items=1)
