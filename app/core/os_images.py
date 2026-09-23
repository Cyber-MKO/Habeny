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
    """Map OS type to LXC configuration"""
    return dict(OS_IMAGES.get(os_type, OS_IMAGES["ubuntu_22_04"]))
