"""
LXC container lifecycle, stats, config generation, health checks and log injection.
"""
import base64
import logging
import random
import re
import shlex
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from typing import Any, Dict, List, Optional

import lxc

from app.core.shell import execute_in_container_shell, run_command
from app.core.validation import validate_container_path

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_system_arch() -> str:
    """Get system architecture (cached for performance)"""
    try:
        result = run_command(["dpkg", "--print-architecture"])
        if result["success"]:
            return result["stdout"]
    except Exception:
        pass

    # Fallback to uname
    result = run_command(["uname", "-m"])
    arch_map = {
        "x86_64": "amd64",
        "aarch64": "arm64",
        "armv7l": "armhf",
        "i386": "i386",
        "i686": "i386"
    }
    return arch_map.get(result["stdout"], "amd64")


def parse_memory_limit(memory_str: str) -> str:
    """
    Parse memory string like '512MB' to bytes as string
    
    Args:
        memory_str: Memory specification (e.g., "512MB", "2GB")
    
    Returns:
        Memory in bytes as string
    """
    # If it's already a number, return as string
    if isinstance(memory_str, (int, float)):
        return str(int(memory_str))

    match = re.match(r"(\d+)([KMG]?B)?", str(memory_str).upper())
    if not match:
        return "536870912"  # Default 512MB in bytes as string

    value, unit = match.groups()
    value = int(value)

    multipliers = {
        "KB": 1024,
        "MB": 1024 * 1024,
        "GB": 1024 * 1024 * 1024,
        None: 1  # bytes or no unit
    }

    return str(value * multipliers.get(unit, 1))


def validate_container_name(name: str) -> bool:
    """
    Validate container name according to LXC naming rules
    
    Args:
        name: Container name to validate
    
    Returns:
        True if valid, False otherwise
    """
    pattern = r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$"
    return bool(re.match(pattern, name)) and len(name) <= 50


def get_container_stats(container_name: str) -> Dict[str, Any]:
    """
    Get comprehensive container statistics
    
    Args:
        container_name: Name of the container
    
    Returns:
        Dict with memory, cpu, network, and process stats
    """
    stats = {}
    try:
        container = lxc.Container(container_name)

        if not container.defined:
            return {"error": "Container not defined"}

        # Get memory stats
        try:
            memory_stats = container.get_cgroup_item("memory.stat")
            if memory_stats:
                stats["memory"] = {
                    "usage": container.get_cgroup_item("memory.usage_in_bytes"),
                    "limit": container.get_cgroup_item("memory.limit_in_bytes"),
                    "swap": container.get_cgroup_item("memory.memsw.usage_in_bytes")
                }
        except Exception as e:
            stats["memory"] = {"error": str(e)}

        # Get CPU stats
        try:
            cpu_stats = container.get_cgroup_item("cpu.stat")
            if cpu_stats:
                stats["cpu"] = cpu_stats
        except Exception as e:
            stats["cpu"] = {"error": str(e)}

        # Get network stats
        try:
            stats["network"] = {
                "interfaces": container.get_interfaces() if container.running else [],
                "ips": container.get_ips() if container.running else []
            }
        except Exception as e:
            stats["network"] = {"error": str(e)}

        # Get process count
        try:
            proc_count = container.get_cgroup_item("pids.current")
            if proc_count:
                stats["processes"] = proc_count
        except Exception as e:
            stats["processes"] = {"error": str(e)}

        # Get uptime
        if container.running:
            stats["uptime_seconds"] = time.time()  # Simplified - track actual start time in production

    except Exception as e:
        stats["error"] = str(e)

    return stats


def get_container_stats_batch(container_names: List[str], max_workers: int = 10) -> Dict[str, Dict[str, Any]]:
    """
    Get stats for multiple containers in parallel
    
    Args:
        container_names: List of container names
        max_workers: Maximum concurrent workers
    
    Returns:
        Dict mapping container names to their stats
    """
    results = {}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_name = {
            executor.submit(get_container_stats, name): name
            for name in container_names
        }

        for future in as_completed(future_to_name):
            name = future_to_name[future]
            try:
                results[name] = future.result(timeout=30)
            except Exception as e:
                results[name] = {"error": str(e)}

    return results


def generate_config(name: str, memory_limit: str, cpu_shares: int, network_config: Dict) -> str:
    """
    Generate LXC configuration file content
    
    Args:
        name: Container name
        memory_limit: Memory limit (e.g., "512MB")
        cpu_shares: CPU shares allocation
        network_config: Additional network configuration
    
    Returns:
        Configuration file content as string
    """
    config = f"""# Container: {name}
lxc.uts.name = {name}
lxc.arch = {get_system_arch()}

# Security
lxc.seccomp.profile = /usr/share/lxc/config/common.seccomp
lxc.apparmor.profile = lxc-container-default

# Network
lxc.net.0.type = veth
lxc.net.0.link = lxcbr0
lxc.net.0.flags = up
lxc.net.0.hwaddr = 00:16:3e:$(openssl rand -hex 3)
lxc.net.0.ipv4.address = auto
lxc.net.0.ipv4.gateway = auto

# Limits
lxc.cgroup.memory.max = {parse_memory_limit(memory_limit)}
lxc.cgroup.cpu.shares = {cpu_shares}

# Root filesystem
lxc.rootfs.path = dir:/var/lib/lxc/{name}/rootfs
lxc.rootfs.backend = dir

# Console
lxc.console.path = none
lxc.tty.max = 2
"""

    # Add custom network config if provided
    for key, value in network_config.items():
        config += f"{key} = {value}\n"

    return config


def setup_agent_health_check(container_name: str) -> Dict[str, Any]:
    """
    Install a health check script and cron job inside the container.

    The script writes /var/lib/siem-agent-status.json every 2 minutes.
    """
    script = r"""#!/bin/bash
set -e

# Only install cron if missing; skip apt-get update to avoid timeout
# when many containers are deployed in parallel
if ! command -v cron >/dev/null 2>&1 && ! command -v crond >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    apt-get install -y cron >/dev/null 2>&1 || true
  fi
fi

mkdir -p /usr/local/bin

cat > /usr/local/bin/siem-agent-health.sh << 'EOS'
#!/bin/bash
set -e
STATUS_FILE="/var/lib/siem-agent-status.json"
SIEM_TYPE="unknown"
RUNNING="false"
DETAIL="unknown"
MANAGER_HOST=""
MANAGER_PORT=""
MANAGER_STATUS="unknown"
MANAGER_REACHABLE="false"

extract_xml_value() {
  local tag="$1"
  local file="$2"
  grep -m1 -E "<${tag}>" "$file" 2>/dev/null | sed -E "s/.*<${tag}>([^<]+)<.*/\1/" | tr -d ' '
}

check_connectivity() {
  local host="$1"
  local port="$2"
  if [ -z "$host" ] || [ -z "$port" ]; then
    echo "unknown"
    return
  fi
  if command -v timeout >/dev/null 2>&1; then
    if timeout 2 bash -c "</dev/tcp/$host/$port" >/dev/null 2>&1; then
      echo "connected"
    else
      echo "unreachable"
    fi
  else
    if (echo > /dev/tcp/$host/$port) >/dev/null 2>&1; then
      echo "connected"
    else
      echo "unreachable"
    fi
  fi
}

if command -v systemctl >/dev/null 2>&1; then
  if systemctl is-active --quiet wazuh-agent; then
    SIEM_TYPE="wazuh"
    RUNNING="true"
    DETAIL="active"
  elif systemctl is-active --quiet ossec-agent; then
    SIEM_TYPE="ossec"
    RUNNING="true"
    DETAIL="active"
  fi
  if [ "$DETAIL" = "unknown" ]; then
    if systemctl status wazuh-agent >/dev/null 2>&1; then
      SIEM_TYPE="wazuh"
      DETAIL="inactive"
    elif systemctl status ossec-agent >/dev/null 2>&1; then
      SIEM_TYPE="ossec"
      DETAIL="inactive"
    fi
  fi
fi

if [ "$SIEM_TYPE" = "unknown" ]; then
  if [ -f /var/ossec/bin/wazuh-control ] || [ -f /var/ossec/bin/wazuh-agentd ]; then
    SIEM_TYPE="wazuh"
    DETAIL=$(/var/ossec/bin/wazuh-control status 2>/dev/null | head -n 1)
  elif [ -f /var/ossec/bin/ossec-control ] || [ -f /var/ossec/bin/ossec-agentd ]; then
    SIEM_TYPE="ossec"
    DETAIL=$(/var/ossec/bin/ossec-control status 2>/dev/null | head -n 1)
  fi
fi

if [ "$SIEM_TYPE" = "unknown" ] && [ -f /usr/share/ossim/agent/agent.py ]; then
  SIEM_TYPE="ossim"
  if pgrep -f "/usr/share/ossim/agent/agent.py" >/dev/null 2>&1; then
    RUNNING="true"
    DETAIL="running"
  else
    RUNNING="false"
    DETAIL="stopped"
  fi
fi

if [ "$SIEM_TYPE" = "unknown" ] && [ -f /opt/utmstack-linux-agent/utmstack_agent_service ]; then
  SIEM_TYPE="utmstack"
  if pgrep -f "utmstack_agent_service" >/dev/null 2>&1; then
    RUNNING="true"
    DETAIL="running"
  else
    RUNNING="false"
    DETAIL="stopped"
  fi
fi

if [ "$SIEM_TYPE" = "unknown" ] && command -v elastic-agent >/dev/null 2>&1; then
  SIEM_TYPE="elastic"
  if systemctl is-active --quiet elastic-agent 2>/dev/null; then
    RUNNING="true"
    DETAIL="active"
  else
    RUNNING="false"
    DETAIL=$(systemctl is-active elastic-agent 2>/dev/null || echo "stopped")
  fi
fi

if [ "$DETAIL" = "unknown" ]; then
  if service wazuh-agent status >/dev/null 2>&1; then
    SIEM_TYPE="wazuh"
    DETAIL=$(service wazuh-agent status 2>/dev/null | head -n 1)
  elif service ossec-agent status >/dev/null 2>&1; then
    SIEM_TYPE="ossec"
    DETAIL=$(service ossec-agent status 2>/dev/null | head -n 1)
  fi
fi

if [ "$SIEM_TYPE" = "wazuh" ] || [ "$SIEM_TYPE" = "ossec" ]; then
  CONFIG_FILE="/var/ossec/etc/ossec.conf"
  if [ -f "$CONFIG_FILE" ]; then
    MANAGER_HOST=$(extract_xml_value "address" "$CONFIG_FILE")
    if [ -z "$MANAGER_HOST" ]; then
      MANAGER_HOST=$(extract_xml_value "server-ip" "$CONFIG_FILE")
    fi
    MANAGER_PORT=$(extract_xml_value "port" "$CONFIG_FILE")
  fi
  if [ -z "$MANAGER_PORT" ]; then
    MANAGER_PORT="1514"
  fi
elif [ "$SIEM_TYPE" = "ossim" ]; then
  CONFIG_FILE="/usr/share/ossim/agent/config.cfg"
  if [ -f "$CONFIG_FILE" ]; then
    MANAGER_HOST=$(grep -m1 -E "^ip=" "$CONFIG_FILE" | cut -d'=' -f2 | tr -d ' ')
    MANAGER_PORT=$(grep -m1 -E "^port=" "$CONFIG_FILE" | cut -d'=' -f2 | tr -d ' ')
  fi
  if [ -z "$MANAGER_PORT" ]; then
    MANAGER_PORT="40001"
  fi
elif [ "$SIEM_TYPE" = "elastic" ]; then
  ELASTIC_CFG="/etc/elastic-agent/fleet.yml"
  if [ -f "$ELASTIC_CFG" ]; then
    MANAGER_HOST=$(grep -m1 'host:' "$ELASTIC_CFG" 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' | head -1)
  fi
  if [ -z "$MANAGER_PORT" ]; then
    MANAGER_PORT="8220"
  fi
elif [ "$SIEM_TYPE" = "utmstack" ]; then
  UTM_PID=$(pgrep -f "utmstack_agent_service" 2>/dev/null | head -1)
  if [ -n "$UTM_PID" ] && [ -f "/proc/$UTM_PID/cmdline" ]; then
    MANAGER_HOST=$(tr '\0' ' ' < "/proc/$UTM_PID/cmdline" 2>/dev/null \
      | grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' | head -1)
  fi
  if [ -z "$MANAGER_HOST" ]; then
    # Fall back: scan the install directory for any config or log referencing the manager
    MANAGER_HOST=$(grep -rohE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' /opt/utmstack-linux-agent/ 2>/dev/null \
      | head -1)
  fi
  if [ -z "$MANAGER_PORT" ]; then
    MANAGER_PORT="9000"
  fi
fi

MANAGER_STATUS=$(check_connectivity "$MANAGER_HOST" "$MANAGER_PORT")
if [ "$MANAGER_STATUS" = "connected" ]; then
  MANAGER_REACHABLE="true"
fi

if echo "$DETAIL" | grep -qi "running\|active"; then
  RUNNING="true"
fi

DETAIL=$(echo "$DETAIL" | tr '"' "'")
LAST_CHECK=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

cat > "$STATUS_FILE" << EOFSTATUS
{"siem_type":"$SIEM_TYPE","running":$RUNNING,"status":"$DETAIL","last_check":"$LAST_CHECK","manager_host":"$MANAGER_HOST","manager_port":"$MANAGER_PORT","manager_status":"$MANAGER_STATUS","manager_reachable":$MANAGER_REACHABLE}
EOFSTATUS
chmod 644 "$STATUS_FILE"
EOS

chmod +x /usr/local/bin/siem-agent-health.sh

echo "*/2 * * * * root /usr/local/bin/siem-agent-health.sh >/var/log/siem-agent-health.log 2>&1" > /etc/cron.d/siem-agent-health
chmod 644 /etc/cron.d/siem-agent-health

if command -v systemctl >/dev/null 2>&1; then
  systemctl enable cron >/dev/null 2>&1 || true
  systemctl restart cron >/dev/null 2>&1 || true
else
  service cron restart >/dev/null 2>&1 || service cron start >/dev/null 2>&1 || true
fi

/usr/local/bin/siem-agent-health.sh >/dev/null 2>&1 || true
"""
    return execute_in_container_shell(container_name, script, timeout=120)


def container_exists(name: str) -> bool:
    """Check if a container exists"""
    return name in lxc.list_containers()


def is_container_running(name: str) -> bool:
    """Check if a container is running"""
    if not container_exists(name):
        return False
    container = lxc.Container(name)
    return container.running


def get_container_state(name: str) -> Optional[str]:
    """Get container state"""
    if not container_exists(name):
        return None
    container = lxc.Container(name)
    return container.state


def start_container_with_retry(name: str, max_attempts: int = 3) -> bool:
    """Start container with retry logic"""
    container = lxc.Container(name)

    for attempt in range(max_attempts):
        try:
            if container.start():
                container.wait("RUNNING", 10)
                return True
            time.sleep(2)
        except Exception as e:
            logger.warning(f"Attempt {attempt + 1} to start {name} failed: {e}")
            time.sleep(2)

    return False


def stop_container_gracefully(name: str, timeout: int = 10) -> bool:
    """Stop container gracefully with fallback to force stop"""
    container = lxc.Container(name)

    if not container.running:
        return True

    # Try graceful shutdown
    if container.shutdown(timeout):
        container.wait("STOPPED", timeout)
        return True

    # Force stop
    logger.warning(f"Graceful shutdown failed for {name}, forcing stop")
    return container.stop()


def build_write_file_script(path: str, content: str, append: bool = False) -> str:
    """Shell snippet that writes `content` to `path` in a container.

    The content travels base64-encoded, so nothing in it (e.g. a line that matches a
    heredoc terminator) can be interpreted by the shell; the path is validated and quoted.
    """
    validate_container_path(path)
    qpath = shlex.quote(path)
    encoded = base64.b64encode(content.encode()).decode()
    operator = ">>" if append else ">"
    return (
        f"mkdir -p \"$(dirname -- {qpath})\"\n"
        f"printf '%s' '{encoded}' | base64 -d {operator} {qpath}\n"
        f"chmod 644 {qpath}\n"
    )


def inject_logs_to_container(container_name: str, log_content: str,
                            destination_path: str, append: bool = False) -> Dict[str, Any]:
    """
    Inject log content into a container
    
    Args:
        container_name: Name of the container
        log_content: Log content to inject
        destination_path: Destination file path
        append: Whether to append or overwrite
    
    Returns:
        Dict with success status
    """
    try:
        script = build_write_file_script(destination_path, log_content, append)
        script += f'echo "Injected $(wc -l < {shlex.quote(destination_path)}) lines to "{shlex.quote(destination_path)}\n'

        result = execute_in_container_shell(container_name, script, timeout=30)

        if result["success"]:
            logger.info(f"Successfully injected logs to {container_name}:{destination_path}")
        else:
            logger.error(f"Failed to inject logs to {container_name}: {result['stderr']}")

        return result

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "stdout": "",
            "stderr": str(e)
        }


def distribute_logs_to_agents(agent_names: List[str], log_files: List[Dict[str, str]],
                              strategy: str = "round_robin") -> Dict[str, Any]:
    """
    Distribute log files to multiple containers
    
    Args:
        agent_names: List of container names
        log_files: List of dicts with 'path' and 'content'
        strategy: Distribution strategy (round_robin, random, all)
    
    Returns:
        Dict with distribution results
    """
    results = {}

    if strategy == "all":
        # Send all logs to all agents
        for agent in agent_names:
            agent_results = []
            for log_file in log_files:
                result = inject_logs_to_container(
                    agent,
                    log_file["content"],
                    log_file["path"],
                    append=True
                )
                agent_results.append(result)
            results[agent] = agent_results

    elif strategy == "round_robin":
        # Distribute logs evenly across agents
        for i, log_file in enumerate(log_files):
            agent = agent_names[i % len(agent_names)]
            result = inject_logs_to_container(
                agent,
                log_file["content"],
                log_file["path"],
                append=True
            )
            if agent not in results:
                results[agent] = []
            results[agent].append(result)

    elif strategy == "random":
        # Randomly distribute logs
        for log_file in log_files:
            agent = random.choice(agent_names)
            result = inject_logs_to_container(
                agent,
                log_file["content"],
                log_file["path"],
                append=True
            )
            if agent not in results:
                results[agent] = []
            results[agent].append(result)

    return results
