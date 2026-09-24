"""
Container networking: host interface detection, macvlan setup and waiting for IPs.
"""
import logging
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.core.lxc_backend import lxc
from app.core.shell import run_command

logger = logging.getLogger(__name__)


def _is_wifi_interface(iface: str) -> bool:
    """Check if a network interface is WiFi (macvlan is incompatible with WiFi)."""
    return os.path.isdir(f"/sys/class/net/{iface}/wireless") or iface.startswith("wl")


def get_host_interface() -> str | None:
    """Return a wired host interface suitable for macvlan.

    Checks the default route first; if that's WiFi, scans for any wired
    interface that is UP.  Returns None if only WiFi is available.
    """
    # Try the default-route interface first
    result = run_command(["ip", "-o", "route", "show", "default"])
    if result["success"] and result["stdout"]:
        parts = result["stdout"].split()
        if "dev" in parts:
            iface = parts[parts.index("dev") + 1]
            if not _is_wifi_interface(iface):
                return iface
            logger.warning(
                f"Default interface {iface} is WiFi — macvlan is incompatible with WiFi adapters"
            )

    # Fall back: look for any wired interface that is UP
    result = run_command(["ip", "-o", "link", "show", "up"])
    if result["success"]:
        for line in result["stdout"].splitlines():
            parts = line.split()
            if len(parts) >= 2:
                iface = parts[1].rstrip(":")
                if iface == "lo":
                    continue
                if not _is_wifi_interface(iface):
                    return iface

    return None


def configure_container_macvlan(container, host_interface: str) -> bool:
    """Configure a stopped container to use macvlan on the host's physical interface.

    This gives the container an IP on the host's network segment instead of
    the default NATed lxcbr0 address.  Required for SIEM agents like OSSEC
    that tie registration to the source IP the manager sees.

    Args:
        container: An lxc.Container object (must be the same instance the
                   caller will later call save_config/start on, otherwise
                   save_config on the caller's copy overwrites these changes).
        host_interface: Name of the host's physical NIC (e.g. "eth0", "ens33").
    """
    if not container.defined or container.running:
        return False
    mac = "00:16:3e:" + ":".join(f"{random.randint(0, 255):02x}" for _ in range(3))
    container.clear_config_item("lxc.net.0")
    container.set_config_item("lxc.net.0.type", "macvlan")
    container.set_config_item("lxc.net.0.macvlan.mode", "bridge")
    container.set_config_item("lxc.net.0.link", host_interface)
    container.set_config_item("lxc.net.0.flags", "up")
    container.set_config_item("lxc.net.0.hwaddr", mac)
    logger.info(f"Configured macvlan on {host_interface} for container {container.name}")
    return True


def wait_for_network(container, timeout: int = 30, check_interval: int = 1) -> bool:
    """
    Wait for container network to be ready

    Args:
        container: LXC container object
        timeout: Maximum wait time in seconds
        check_interval: Time between checks in seconds

    Returns:
        True if network is ready, False if timeout
    """
    start_time = time.time()

    while time.time() - start_time < timeout:
        try:
            ips = container.get_ips()
            if ips:
                logger.info(f"Container {container.name} network ready with IPs: {ips}")
                return True
        except Exception as e:
            logger.debug(f"Network check failed: {e}")

        time.sleep(check_interval)

    logger.warning(f"Container {container.name} network not ready after {timeout}s")
    return False


def wait_for_network_batch(containers: list, timeout: int = 30, max_workers: int = 10) -> dict[str, bool]:
    """
    Wait for multiple containers' networks in parallel

    Args:
        containers: List of LXC container objects
        timeout: Maximum wait time per container
        max_workers: Maximum concurrent workers

    Returns:
        Dict mapping container names to network ready status
    """
    results = {}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_container = {
            executor.submit(wait_for_network, container, timeout): container
            for container in containers
        }

        for future in as_completed(future_to_container):
            container = future_to_container[future]
            try:
                results[container.name] = future.result()
            except Exception as e:
                logger.error(f"Error waiting for network on {container.name}: {e}")
                results[container.name] = False

    return results


def get_container_ips(container_name: str, timeout: int = 30) -> list[str]:
    """
    Get container IP addresses with retry logic

    Args:
        container_name: Name of the container
        timeout: Maximum wait time

    Returns:
        List of IP addresses
    """
    container = lxc.Container(container_name)

    if not container.running:
        return []

    if wait_for_network(container, timeout):
        return container.get_ips()

    return []
