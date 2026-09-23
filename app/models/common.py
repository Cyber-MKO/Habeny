"""
Shared validation patterns/helpers and utc_now.
"""
import re
from datetime import datetime, timezone

from app.core.validation import (
    validate_container_path,
    validate_group,
    validate_host,
    validate_token,
    validate_version,
)

IP_PATTERN = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")


HOSTNAME_PATTERN = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?)*$")


ALPHANUM_START_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")


CONTAINER_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")


def validate_absolute_path(v: str) -> str:
    if not v.startswith('/'):
        raise ValueError('Path must be absolute (start with /)')
    if '..' in v:
        raise ValueError('Path cannot contain ..')
    # Only characters that are inert in shell scripts (the path is written into one)
    return validate_container_path(v)


def optional(check):
    """Wrap a strict validator so None/"" (not provided) pass through."""
    def validator_fn(v):
        return v if v in (None, "") else check(v)
    return validator_fn


INSTALL_FIELD_CHECKS = {
    "siem_ip": optional(validate_host),
    "siem_version": optional(validate_version),
    "siem_auth_key": optional(validate_token),
    "agent_group": optional(validate_group),
}


def validate_alphanumeric_name(v: str) -> str:
    if not ALPHANUM_START_PATTERN.match(v):
        raise ValueError("Name must start with alphanumeric and contain only alphanumeric, underscore, or hyphen")
    return v


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
