"""
Authentication request models.
"""
from typing import Literal

from pydantic import BaseModel, Field

USERNAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=256)


class SetupRequest(BaseModel):
    """First-run creation of the admin account."""
    setup_token: str = Field(..., min_length=1, max_length=128)
    username: str = Field(..., min_length=3, max_length=32, pattern=USERNAME_PATTERN)
    password: str = Field(..., min_length=8, max_length=256)


class PasswordChangeRequest(BaseModel):
    """A signed-in user changing their own password."""
    current_password: str = Field(..., min_length=1, max_length=256)
    new_password: str = Field(..., min_length=8, max_length=256)


class UserCreateRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=32, pattern=USERNAME_PATTERN)
    password: str = Field(..., min_length=8, max_length=256)
    role: Literal["viewer", "operator", "admin"] = "viewer"  # least privilege by default


class UserUpdateRequest(BaseModel):
    role: Literal["viewer", "operator", "admin"]


class PasswordResetRequest(BaseModel):
    """An admin setting a new password for another user."""
    new_password: str = Field(..., min_length=8, max_length=256)
