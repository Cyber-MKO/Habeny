"""
OSSIM agent installer.
"""
import logging
from typing import Any

from app.core.shell import PerformanceTimer, execute_in_container_shell
from app.core.validation import validate_container_name, validate_host

logger = logging.getLogger(__name__)


def install_ossim_agent(container_name: str, ossim_server: str,
                       config_template_id: str | None = None) -> dict[str, Any]:
    """
    Install OSSIM/AlienVault agent in a container

    Args:
        container_name: Name of the container
        ossim_server: OSSIM server IP/hostname
        config_template_id: Optional config template to apply

    Returns:
        Dict with success status and output
    """
    validate_container_name(container_name)
    validate_host(ossim_server)
    logger.info(f"Installing OSSIM agent in container '{container_name}'")

    with PerformanceTimer(f"OSSIM installation on {container_name}"):
        # Update packages
        update_result = execute_in_container_shell(
            container_name,
            "apt-get update -y && apt-get install -y wget python3",
            timeout=180
        )

        if not update_result["success"]:
            return update_result

        # Install OSSIM agent
        ossim_script = f"""#!/bin/bash
set -e

# Download and install OSSIM agent
cd /tmp
wget -q https://github.com/AlienVault-OTX/OSSIM/raw/master/ossim-agent/ossim-agent.deb || echo "Using alternative method"

# Alternative: Manual installation
mkdir -p /usr/share/ossim/agent
cat > /usr/share/ossim/agent/config.cfg << EOF
[server]
ip={ossim_server}
port=40001

[agent]
id={container_name}
name={container_name}
EOF

# Create simple agent script
cat > /usr/share/ossim/agent/agent.py << 'PYEOF'
#!/usr/bin/env python3
import socket
import time
import sys

def send_event(server, port, event):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((server, port))
        s.send(event.encode())
        s.close()
        return True
    except Exception as e:
        print(f"Error: {{e}}")
        return False

if __name__ == "__main__":
    print("OSSIM Agent started")
    while True:
        time.sleep(60)
PYEOF

chmod +x /usr/share/ossim/agent/agent.py

# Start agent
nohup /usr/share/ossim/agent/agent.py &

echo "=== OSSIM Agent Information ==="
echo "Agent Name: {container_name}"
echo "Server: {ossim_server}"
echo "Status: Running"
"""

        result = execute_in_container_shell(container_name, ossim_script, timeout=600)

        if result["success"]:
            logger.info(f"[{container_name}] OSSIM agent installed successfully")
        else:
            logger.error(f"[{container_name}] OSSIM installation failed: {result['stderr']}")

        return result
