"""
Authentication request models.
"""
from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=256)


class SetupRequest(BaseModel):
    """First-run creation of the admin account."""
    username: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    password: str = Field(..., min_length=8, max_length=256)
