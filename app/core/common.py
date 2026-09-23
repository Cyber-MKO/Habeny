"""
Shared helpers: privilege check and LXC host introspection.
"""

from fastapi import HTTPException

from app.core.lxc_backend import has_lxc_access, lxc


def check_root():
    """Container operations need LXC access: root (direct mode) or the privileged helper."""
    if not has_lxc_access():
        raise HTTPException(
            status_code=403,
            detail="Container operations need root or the habeny LXC helper (HABENY_LXC_BACKEND=helper)."
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
