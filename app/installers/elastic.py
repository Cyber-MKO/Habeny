"""
Elastic Agent installer (Fleet enrollment).
"""
import logging
import shlex
from typing import Any, Dict, Optional

from app.core.shell import PerformanceTimer, execute_in_container_shell
from app.core.validation import validate_container_name, validate_host, validate_token, validate_version
from app.installers.cache import AGENT_CACHE_DIR, copy_to_container, ensure_cached

logger = logging.getLogger(__name__)


def install_elastic_agent(container_name: str, fleet_url: str,
                          enrollment_token: str,
                          version: str = "9.0.2",
                          config_template_id: Optional[str] = None) -> Dict[str, Any]:
    """Install Elastic Agent in a container via Fleet enrollment."""
    validate_container_name(container_name)
    validate_host(fleet_url)  # a host: the script builds https://<host>:8220
    validate_token(enrollment_token)
    validate_version(version)
    logger.info(f"Installing Elastic Agent in container '{container_name}'")

    deb_file = f"elastic-agent-{version}-amd64.deb"
    deb_url = f"https://artifacts.elastic.co/downloads/beats/elastic-agent/{deb_file}"
    container_deb = f"/tmp/{deb_file}"

    with PerformanceTimer(f"Elastic Agent installation on {container_name}"):
        # Download .deb to host cache once, then copy into container
        try:
            cached = ensure_cached(
                deb_file,
                ["wget", "-q", "-O", str(AGENT_CACHE_DIR / deb_file), deb_url],
                timeout=180,
            )
            if not copy_to_container(container_name, cached, container_deb):
                logger.warning(f"[{container_name}] Cache copy failed, will download inside container")
                container_deb = None
        except Exception as e:
            logger.warning(f"[{container_name}] Host-side cache failed ({e}), will download inside container")
            container_deb = None

        # Fall back to in-container download if cache copy failed
        download_block = ""
        if container_deb is None:
            container_deb = f"/tmp/{deb_file}"
            download_block = f"""
if command -v curl >/dev/null 2>&1; then
  curl -L -o "{container_deb}" "{deb_url}"
elif command -v wget >/dev/null 2>&1; then
  wget -q -O "{container_deb}" "{deb_url}"
else
  echo "ERROR: neither curl nor wget available"
  exit 1
fi
"""

        apt_block = ""
        if download_block:
            apt_block = """
ensure_dns() {
  GW_DNS=$(ip route | awk '/default/ {print $3; exit}')
  {
    if [ -n "$GW_DNS" ]; then echo "nameserver $GW_DNS"; fi
    echo "nameserver 1.1.1.1"
    echo "nameserver 8.8.8.8"
    echo "options timeout:1 attempts:3"
  } > /etc/resolv.conf
}
wait_for_dns() {
  local attempts=20
  while [ $attempts -gt 0 ]; do
    if getent ahostsv4 archive.ubuntu.com >/dev/null 2>&1; then return 0; fi
    sleep 2; attempts=$((attempts-1))
  done
  return 1
}
ensure_dns
wait_for_dns || ensure_dns
apt-get update -y
apt-get install -y curl wget
"""

        elastic_script = f"""#!/bin/bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

FLEET_URL={shlex.quote(fleet_url)}
ENROLLMENT_TOKEN={shlex.quote(enrollment_token)}
{apt_block}{download_block}
ELASTIC_AGENT_FLAVOR=servers dpkg -i "{container_deb}" || apt-get install -f -y
rm -f "{container_deb}"

systemctl enable elastic-agent
systemctl start elastic-agent

elastic-agent enroll \\
  --url="https://$FLEET_URL:8220" \\
  --enrollment-token="$ENROLLMENT_TOKEN" \\
  --insecure

echo "=== Elastic Agent Information ==="
echo "Agent Name: {container_name}"
echo "Fleet URL: $FLEET_URL"
echo "Status: $(systemctl is-active elastic-agent 2>/dev/null || echo unknown)"
"""
        result = execute_in_container_shell(container_name, elastic_script, timeout=600)

        if result["success"]:
            logger.info(f"[{container_name}] Elastic Agent installed successfully")
        else:
            logger.error(f"[{container_name}] Elastic Agent installation failed: {result['stderr']}")

        return result
