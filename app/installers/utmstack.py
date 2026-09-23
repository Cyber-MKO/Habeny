"""
UTMstack agent installer.
"""
import logging
import shlex
from typing import Any, Dict, Optional

from app.core.shell import PerformanceTimer, execute_in_container, execute_in_container_shell
from app.core.validation import validate_container_name, validate_host, validate_token
from app.installers.cache import AGENT_CACHE_DIR, copy_to_container, ensure_cached

logger = logging.getLogger(__name__)


def install_utmstack_agent(container_name: str, utmstack_server: str,
                           auth_key: str,
                           config_template_id: Optional[str] = None) -> Dict[str, Any]:
    """Install UTMstack agent in a container."""
    validate_container_name(container_name)
    validate_host(utmstack_server)
    validate_token(auth_key)
    logger.info(f"Installing UTMstack agent in container '{container_name}'")

    binary_name = f"utmstack_agent_service_{utmstack_server}"
    binary_url = f"https://{utmstack_server}:9001/private/dependencies/agent/utmstack_agent_service"
    container_bin = "/opt/utmstack-linux-agent/utmstack_agent_service"

    with PerformanceTimer(f"UTMstack installation on {container_name}"):
        # Cache the binary on the host, then copy into the container
        copied = False
        try:
            cached = ensure_cached(
                binary_name,
                ["wget", "--no-check-certificate", "-q", "-O",
                 str(AGENT_CACHE_DIR / binary_name), binary_url],
                timeout=120,
            )
            if cached.stat().st_size < 1000:
                logger.warning(f"Cached {binary_name} too small ({cached.stat().st_size}B), removing")
                cached.unlink(missing_ok=True)
                raise RuntimeError("Cached file appears corrupt")
            execute_in_container(container_name, "mkdir -p /opt/utmstack-linux-agent", timeout=10)
            if copy_to_container(container_name, cached, container_bin):
                execute_in_container(container_name, f"chmod 755 {container_bin}", timeout=10)
                copied = True
                logger.info(f"[{container_name}] UTMstack binary copied from cache")
        except Exception as e:
            logger.warning(f"[{container_name}] Host-side cache failed ({e}), will download inside container")

        # Fall back to in-container download if cache copy failed
        download_block = ""
        if not copied:
            download_block = f"""
apt-get update -y
apt-get install -y wget
mkdir -p /opt/utmstack-linux-agent
wget --no-check-certificate -q -O {container_bin} "{binary_url}"
chmod 755 {container_bin}
"""

        utmstack_script = f"""#!/bin/bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

MANAGER_IP={shlex.quote(utmstack_server)}
AUTH_KEY={shlex.quote(auth_key)}

# The install command downloads dependencies internally via wget
apt-get update -y >/dev/null 2>&1 || true
apt-get install -y wget >/dev/null 2>&1 || true
{download_block}
{container_bin} install "$MANAGER_IP" "$AUTH_KEY" yes

echo "=== UTMstack Agent Information ==="
echo "Agent Name: {container_name}"
echo "Server: $MANAGER_IP"
echo "Status: Installed"
"""
        result = execute_in_container_shell(container_name, utmstack_script, timeout=600)

        if result["success"]:
            logger.info(f"[{container_name}] UTMstack agent installed successfully")
        else:
            logger.error(f"[{container_name}] UTMstack installation failed: {result.get('stderr') or result.get('stdout', '')[-500:]}")

        return result
