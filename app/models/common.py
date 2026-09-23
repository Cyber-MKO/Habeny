"""
Shared validation patterns/helpers and utc_now.
"""
import re
from datetime import datetime, timezone

IP_PATTERN = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")


HOSTNAME_PATTERN = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?)*$")


ALPHANUM_START_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")


CONTAINER_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")


def validate_absolute_path(v: str) -> str:
    if not v.startswith('/'):
        raise ValueError('Path must be absolute (start with /)')
    if '..' in v:
        raise ValueError('Path cannot contain ..')
    return v


def validate_alphanumeric_name(v: str) -> str:
    if not ALPHANUM_START_PATTERN.match(v):
        raise ValueError("Name must start with alphanumeric and contain only alphanumeric, underscore, or hyphen")
    return v


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
