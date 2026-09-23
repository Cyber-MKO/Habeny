"""
OSSEC agent installer (Atomicorp repository + agent-auth).
"""
import logging
from typing import Any, Dict, Optional

from app.core.shell import PerformanceTimer, execute_in_container_shell
from app.core.validation import validate_container_name, validate_host

logger = logging.getLogger(__name__)


def install_ossec_agent(container_name: str, ossec_server: str,
                       config_template_id: Optional[str] = None) -> Dict[str, Any]:
    """Install OSSEC agent in a container using the Atomicorp installer."""
    validate_container_name(container_name)
    validate_host(ossec_server)
    logger.info(f"Installing OSSEC agent in container '{container_name}'")

    with PerformanceTimer(f"OSSEC installation on {container_name}"):
        ossec_script = """#!/bin/bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

MANAGER_IP="__MANAGER_IP__"
MANAGER_PORT="1516"
OSSEC_CONF="/var/ossec/etc/ossec.conf"

APT_OPTS="-o Acquire::ForceIPv4=true -o Acquire::Retries=5 -o Acquire::http::Timeout=20 -o Acquire::https::Timeout=20"

ensure_dns() {
  GW_DNS=$(ip route | awk '/default/ {print $3; exit}')
  {
    if [ -n "$GW_DNS" ]; then
      echo "nameserver $GW_DNS"
    fi
    echo "nameserver 1.1.1.1"
    echo "nameserver 8.8.8.8"
    echo "options timeout:1 attempts:3"
  } > /etc/resolv.conf
}

if ! getent ahostsv4 archive.ubuntu.com >/dev/null 2>&1; then
  ensure_dns
fi

if [ -f /etc/gai.conf ] && ! grep -q "precedence ::ffff:0:0/96" /etc/gai.conf; then
  echo "precedence ::ffff:0:0/96  100" >> /etc/gai.conf
fi

cat > /etc/apt/apt.conf.d/99force-ipv4 << EOF
Acquire::ForceIPv4 "true";
Acquire::Retries "5";
Acquire::http::Timeout "20";
Acquire::https::Timeout "20";
EOF

wait_for_dns() {
  local attempts=20
  while [ $attempts -gt 0 ]; do
    if getent ahostsv4 archive.ubuntu.com >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
    attempts=$((attempts-1))
  done
  return 1
}

apt_update() {
  rm -rf /var/lib/apt/lists/*
  apt-get $APT_OPTS update -y | tee /tmp/apt-update.log
  if grep -E "Failed to fetch|Temporary failure resolving|Could not resolve" /tmp/apt-update.log >/dev/null; then
    return 1
  fi
  return 0
}

apt_ok=0
for i in $(seq 1 5); do
  ensure_dns
  wait_for_dns || true
  if apt_update; then
    apt_ok=1
    break
  fi
  sleep 3
done
if [ "$apt_ok" -ne 1 ]; then
  echo "apt-get update failed after retries"
  exit 1
fi

apt-get $APT_OPTS install -y --fix-missing \
  build-essential make zlib1g-dev libpcre2-dev libevent-dev \
  libssl-dev libsystemd-dev wget expect bsdutils

# --- Atomicorp repository setup via their official installer ---
# The installer handles GPG key import, sources.list, and apt configuration
# internally.  This is the only method that reliably sets up the trust chain
# for the Atomicorp apt repository on Ubuntu 22.04.
wget -q -O /tmp/atomic_installer.sh https://updates.atomicorp.com/installers/atomic
chmod +x /tmp/atomic_installer.sh

if command -v expect >/dev/null 2>&1; then
  expect -c '
    set timeout 120
    spawn bash /tmp/atomic_installer.sh
    expect {
      "yes/no" { send "yes\\r"; exp_continue }
      eof
    }
  '
else
  yes | bash /tmp/atomic_installer.sh
fi
rm -f /tmp/atomic_installer.sh

apt-get $APT_OPTS update -y

apt-get $APT_OPTS install -y ossec-hids-agent

if [ ! -f "$OSSEC_CONF" ]; then
  echo "OSSEC config not found at $OSSEC_CONF"
  exit 1
fi

cp "$OSSEC_CONF" "$OSSEC_CONF.bak"
sed -i "s|<server-ip>.*</server-ip>|<server-ip>$MANAGER_IP</server-ip>|g" "$OSSEC_CONF"

if /var/ossec/bin/agent-auth -m "$MANAGER_IP" -A "$(hostname)" -p "$MANAGER_PORT" 2>&1; then
  echo "Agent registered successfully"
else
  echo "WARNING: agent-auth registration failed."
  echo "If agents are behind NAT, the OSSEC manager must be configured with:"
  echo "  <auth><use_source_ip>no</use_source_ip></auth>"
  echo "in its ossec.conf so agents register with 'any' instead of the NAT IP."
  echo "Alternatively, connect the host via a wired (non-WiFi) interface and"
  echo "redeploy so macvlan networking can give each container a unique IP."
fi

/var/ossec/bin/ossec-control restart || true

echo "=== OSSEC Agent Information ==="
echo "Agent Name: __CONTAINER_NAME__"
echo "Server: __MANAGER_IP__"
echo "Status: $(/var/ossec/bin/ossec-control status 2>/dev/null || echo 'unknown')"
"""
        ossec_script = (
            ossec_script
            .replace("__MANAGER_IP__", ossec_server)
            .replace("__CONTAINER_NAME__", container_name)
        )

        result = execute_in_container_shell(container_name, ossec_script, timeout=900)

        if result["success"]:
            logger.info(f"[{container_name}] OSSEC agent installed successfully")
        else:
            logger.error(f"[{container_name}] OSSEC installation failed: {result['stderr']}")

        return result
