"""
Container OS images offered by the platform (LXC "download" template arguments).
Shared by the app and the privileged helper, which only creates these images.
"""
OS_IMAGES = {
    "ubuntu_22_04": {"distro": "ubuntu", "release": "jammy", "arch": "amd64"},
    "ubuntu_20_04": {"distro": "ubuntu", "release": "focal", "arch": "amd64"},
    "debian_11": {"distro": "debian", "release": "bullseye", "arch": "amd64"},
}


def get_os_config(os_type: str) -> dict:
    """The LXC image for an OS type. An unknown type is an error, never a silent substitute."""
    if os_type not in OS_IMAGES:
        raise ValueError(f"Unsupported OS type {os_type!r}; choose one of: {', '.join(OS_IMAGES)}")
    return dict(OS_IMAGES[os_type])
