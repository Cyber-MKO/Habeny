"""
Wazuh agent installer.
"""
import asyncio
import logging
import shlex
from typing import Any

from app.core.shell import PerformanceTimer, execute_in_container_shell
from app.core.validation import validate_container_name, validate_group, validate_host, validate_version
from app.installers.cache import AGENT_CACHE_DIR, copy_to_container, ensure_cached

logger = logging.getLogger(__name__)


def install_wazuh_agent(container_name: str, wazuh_manager: str, agent_group: str,
                       version: str = "4.14.2", config_template_id: str | None = None) -> dict[str, Any]:
    """Install Wazuh agent in a container using a direct .deb download (cached)."""
    validate_container_name(container_name)
    validate_host(wazuh_manager)
    validate_group(agent_group)
    validate_version(version)
    logger.info(f"Installing Wazuh agent {version} in container '{container_name}'")

    # The Wazuh .deb URL includes a patch suffix (-1); try the exact version first
    deb_name = f"wazuh-agent_{version}-1_amd64.deb"
    deb_url = f"https://packages.wazuh.com/4.x/apt/pool/main/w/wazuh-agent/{deb_name}"
    container_deb = f"/tmp/{deb_name}"

    with PerformanceTimer(f"Wazuh installation on {container_name}"):
        # Download .deb to host cache once, then copy into container
        try:
            cached = ensure_cached(
                deb_name,
                ["wget", "-q", "-O", str(AGENT_CACHE_DIR / deb_name), deb_url],
                timeout=180,
            )
            if not copy_to_container(container_name, cached, container_deb):
                logger.warning(f"[{container_name}] Cache copy failed, will download inside container")
                container_deb = None
        except Exception as e:
            logger.warning(f"[{container_name}] Host-side cache failed ({e}), will download inside container")
            container_deb = None

        download_block = ""
        if container_deb is None:
            container_deb = f"/tmp/{deb_name}"
            download_block = f"""
if command -v curl >/dev/null 2>&1; then
  curl -sL -o "{container_deb}" "{deb_url}"
elif command -v wget >/dev/null 2>&1; then
  wget -q -O "{container_deb}" "{deb_url}"
else
  echo "ERROR: neither curl nor wget available"
  exit 1
fi
"""

        wazuh_script = f"""#!/bin/bash
set -e
export DEBIAN_FRONTEND=noninteractive

export WAZUH_MANAGER={shlex.quote(wazuh_manager)}
export WAZUH_AGENT_GROUP={shlex.quote(agent_group)}
export WAZUH_AGENT_NAME={shlex.quote(container_name)}
{download_block}
dpkg -i "{container_deb}" || apt-get install -f -y
rm -f "{container_deb}"

# Configure agent
sed -i "s|<address>.*</address>|<address>{wazuh_manager}</address>|" /var/ossec/etc/ossec.conf 2>/dev/null || true
sed -i "s|<config-profile>.*</config-profile>|<config-profile>{agent_group}</config-profile>|" /var/ossec/etc/ossec.conf 2>/dev/null || true
echo "{container_name}" > /var/ossec/etc/.agent_name 2>/dev/null || true

systemctl daemon-reload 2>/dev/null || true
systemctl enable wazuh-agent 2>/dev/null || true
systemctl start wazuh-agent 2>/dev/null || true
sleep 3

systemctl status wazuh-agent --no-pager 2>/dev/null || service wazuh-agent status 2>/dev/null || /var/ossec/bin/wazuh-control status

echo "=== Wazuh Agent Information ==="
echo "Agent Name: {container_name}"
echo "Manager: {wazuh_manager}"
echo "Group: {agent_group}"
echo "Version: {version}"
AGENT_ID=$(grep 'id=' /var/ossec/etc/client.keys 2>/dev/null | cut -d' ' -f2 | cut -d'"' -f1 2>/dev/null || echo 'Pending registration')
echo "Agent ID: $AGENT_ID"
"""

        wazuh_result = execute_in_container_shell(container_name, wazuh_script, timeout=600)

        # Check if agent registered with manager
        if wazuh_result["success"]:
            logger.info(f"[{container_name}] Wazuh agent installed successfully")

            # Verify installation
            check_result = execute_in_container_shell(
                container_name,
                "sleep 5 && systemctl is-active wazuh-agent 2>/dev/null && echo 'Agent active' || echo 'Agent inactive'",
                timeout=30
            )
            wazuh_result["stdout"] += f"\n\nVerification: {check_result['stdout']}"
        else:
            logger.error(f"[{container_name}] Wazuh agent installation failed: {wazuh_result['stderr']}")

        return wazuh_result


async def install_wazuh_on_create(container_name: str, wazuh_manager: str,
                                 agent_group: str, version: str):
    """
    Background task to install Wazuh after container creation

    Args:
        container_name: Name of the container
        wazuh_manager: Wazuh manager IP/hostname
        agent_group: Wazuh agent group
        version: Wazuh version to install
    """
    # Wait a bit for container to stabilize
    await asyncio.sleep(5)

    try:
        result = install_wazuh_agent(container_name, wazuh_manager, agent_group, version)

        # Log the result
        if result["success"]:
            logger.info(f"[Background Task] Wazuh agent installed successfully in container '{container_name}'")
            logger.info(f"  Manager: {wazuh_manager}, Group: {agent_group}")
            if result["stdout"]:
                logger.debug(f"  Output: {result['stdout'][:200]}...")
        else:
            logger.error(f"[Background Task] Failed to install Wazuh agent in container '{container_name}'")
            logger.error(f"  Error: {result['stderr']}")
    except Exception as e:
        logger.error(f"[Background Task] Exception installing Wazuh in '{container_name}': {str(e)}")
