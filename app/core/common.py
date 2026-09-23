"""
Shared helpers: privilege check and LXC host introspection.
"""
import os

import lxc
from fastapi import HTTPException


def check_root():
    if os.geteuid() != 0:
        raise HTTPException(
            status_code=403,
            detail="This operation requires root privileges. Run with sudo."
        )
    return True


def get_lxc_version() -> str:
    """Return LXC version, guarding for API differences."""
    version_attr = getattr(lxc, "version", None)
    if callable(version_attr):
        return version_attr()
    if version_attr is None:
        return "unknown"
    return str(version_attr)


def get_lxc_default_config_path() -> str:
    """Return LXC default config path if available."""
    path_attr = getattr(lxc, "default_config_path", None)
    if callable(path_attr):
        return path_attr()
    if path_attr is None:
        return "unknown"
    return str(path_attr)
