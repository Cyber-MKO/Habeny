import subprocess
import json
import re
import os
import time
import logging
import asyncio
import tempfile
import random
import shutil
from typing import List, Dict, Any, Optional, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache, wraps
from pathlib import Path
from datetime import datetime, timedelta
import lxc

# Configure logging
logger = logging.getLogger(__name__)

# ===== DECORATORS AND HELPERS =====

def retry(max_attempts: int = 3, delay: float = 1.0, backoff: float = 2.0):
    """Retry decorator with exponential backoff"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            attempts = 0
            current_delay = delay
            
            while attempts < max_attempts:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    attempts += 1
                    if attempts >= max_attempts:
                        logger.error(f"Function {func.__name__} failed after {max_attempts} attempts: {e}")
                        raise
                    logger.warning(f"Attempt {attempts} failed for {func.__name__}: {e}. Retrying in {current_delay}s...")
                    time.sleep(current_delay)
                    current_delay *= backoff
            
        return wrapper
    return decorator

class PerformanceTimer:
    """Context manager for timing operations"""
    
    def __init__(self, operation_name: str, log_result: bool = True):
        self.operation_name = operation_name
        self.log_result = log_result
        self.start_time = None
        self.end_time = None
    
    def __enter__(self):
        self.start_time = time.time()
        logger.info(f"Starting: {self.operation_name}")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end_time = time.time()
        elapsed = self.end_time - self.start_time
        if self.log_result:
            logger.info(f"Completed: {self.operation_name} in {elapsed:.2f}s")
        return False
    
    @property
    def elapsed(self) -> float:
        if self.end_time is not None and self.start_time is not None:
            return self.end_time - self.start_time
        return 0.0

# ===== BASIC UTILITY FUNCTIONS =====

def run_command(cmd: List[str], capture_output: bool = True, input_text: str = None, 
                timeout: int = 300, env: Dict[str, str] = None) -> Dict[str, Any]:
    """Run a shell command and return a result dict with success, stdout, stderr, returncode."""
    try:
        process_env = os.environ.copy()
        if env:
            process_env.update(env)
        
        kwargs: Dict[str, Any] = {
            "text": True, "check": True, "timeout": timeout, "env": process_env
        }
        if input_text is not None:
            kwargs["input"] = input_text
        if capture_output:
            kwargs["capture_output"] = True

        result = subprocess.run(cmd, **kwargs)

        if capture_output:
            return {
                "success": True,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
                "returncode": result.returncode
            }
        return {"success": True}
    except subprocess.TimeoutExpired as e:
        return {
            "success": False,
            "error": f"Command timeout after {timeout}s",
            "stdout": e.stdout.strip() if e.stdout else "",
            "stderr": e.stderr.strip() if e.stderr else "",
            "returncode": -1
        }
    except subprocess.CalledProcessError as e:
        return {
            "success": False,
            "error": str(e),
            "stdout": e.stdout.strip() if e.stdout else "",
            "stderr": e.stderr.strip() if e.stderr else "",
            "returncode": e.returncode
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "stdout": "",
            "stderr": "",
            "returncode": 1
        }

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

# ===== CONTAINER STATS AND MONITORING =====

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

# ===== CONFIGURATION GENERATION =====

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

# ===== CONTAINER COMMAND EXECUTION =====

@retry(max_attempts=3, delay=2.0)
def execute_in_container(container_name: str, command: str, env: Dict[str, str] = None,
                         timeout: int = 300) -> Dict[str, Any]:
    """
    Execute command in container using lxc-attach
    
    Args:
        container_name: Name of the container
        command: Command to execute
        env: Optional environment variables
        timeout: Command timeout in seconds
    
    Returns:
        Dict with success, stdout, stderr, returncode
    """
    try:
        # Build command
        cmd = ["lxc-attach", "-n", container_name]

        # Add environment variables before --
        if env:
            for key, value in env.items():
                cmd.extend(["-v", f"{key}={value}"])

        # Add the actual command after --
        cmd.extend(["--", "bash", "-c", command])
        
        # Execute
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "returncode": result.returncode
        }
        
    except subprocess.TimeoutExpired as e:
        return {
            "success": False,
            "stdout": e.stdout.decode() if e.stdout else "",
            "stderr": f"Command timeout after {timeout}s",
            "returncode": -1
        }
    except Exception as e:
        return {
            "success": False,
            "stdout": "",
            "stderr": str(e),
            "returncode": 1
        }

def execute_in_container_shell(container_name: str, command: str, env: Dict[str, str] = None,
                               timeout: int = 300) -> Dict[str, Any]:
    """
    Execute shell script in container with better error handling
    
    Args:
        container_name: Name of the container
        command: Shell script to execute
        env: Optional environment variables
        timeout: Script timeout in seconds
    
    Returns:
        Dict with success, stdout, stderr, returncode
    """
    try:
        # Create a temporary script
        script_content = f"""#!/bin/bash
set -o pipefail
{command}
"""
        
        # Create temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
            f.write(script_content)
            script_path = f.name
        
        os.chmod(script_path, 0o755)
        
        # Prepare environment variables
        env_args = []
        if env:
            for key, value in env.items():
                env_args.extend(["-v", f"{key}={value}"])
        
        # Copy script to container
        container_script_path = f"/tmp/script_{os.path.basename(script_path)}"
        
        with open(script_path, 'r') as f:
            script_data = f.read()
        
        copy_cmd = ["lxc-attach", "-n", container_name, "--", "bash", "-c", 
                   f"cat > {container_script_path} && chmod +x {container_script_path}"]
        
        copy_result = subprocess.run(
            copy_cmd,
            input=script_data,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if copy_result.returncode != 0:
            os.unlink(script_path)
            return {
                "success": False,
                "stdout": "",
                "stderr": f"Failed to copy script to container: {copy_result.stderr}",
                "returncode": copy_result.returncode
            }
        
        # Execute the script in container (env args before --)
        exec_cmd = ["lxc-attach", "-n", container_name] + env_args + ["--", "bash", container_script_path]
        
        result = subprocess.run(
            exec_cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        
        # Clean up
        os.unlink(script_path)
        subprocess.run(
            ["lxc-attach", "-n", container_name, "--", "rm", "-f", container_script_path],
            capture_output=True,
            timeout=10
        )
        
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "returncode": result.returncode
        }
        
    except subprocess.TimeoutExpired as e:
        return {
            "success": False,
            "stdout": e.stdout.decode() if e.stdout else "",
            "stderr": f"Script timeout after {timeout}s",
            "returncode": -1
        }
    except Exception as e:
        return {
            "success": False,
            "stdout": "",
            "stderr": str(e),
            "returncode": 1
        }


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

# ===== CONTAINER NETWORK UTILITIES =====

def _is_wifi_interface(iface: str) -> bool:
    """Check if a network interface is WiFi (macvlan is incompatible with WiFi)."""
    return os.path.isdir(f"/sys/class/net/{iface}/wireless") or iface.startswith("wl")


def get_host_interface() -> Optional[str]:
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
    mac = "00:16:3e:%02x:%02x:%02x" % (
        random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)
    )
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

def wait_for_network_batch(containers: List, timeout: int = 30, max_workers: int = 10) -> Dict[str, bool]:
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

def get_container_ips(container_name: str, timeout: int = 30) -> List[str]:
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

# ===== AGENT PACKAGE CACHE =====

AGENT_CACHE_DIR = Path("/var/lib/lxc-siem-platform/agent-cache")
AGENT_CACHE_DIR.mkdir(parents=True, exist_ok=True)

_cache_lock = __import__("threading").Lock()


def _ensure_cached(filename: str, download_cmd: List[str], timeout: int = 120) -> Path:
    """Download a file to the host cache if it doesn't already exist.

    Thread-safe: concurrent containers wait for the first download to finish
    rather than downloading in parallel.
    Returns the path to the cached file.
    """
    cached = AGENT_CACHE_DIR / filename
    with _cache_lock:
        if cached.exists() and cached.stat().st_size > 0:
            logger.info(f"Agent cache hit: {filename}")
            return cached
        logger.info(f"Agent cache miss — downloading {filename}")
        result = run_command(download_cmd, timeout=timeout)
        if not result["success"]:
            raise RuntimeError(f"Failed to download {filename}: {result.get('error') or result.get('stderr')}")
        if not cached.exists():
            raise RuntimeError(f"Download command succeeded but {cached} not found")
        logger.info(f"Cached {filename} ({cached.stat().st_size} bytes)")
    return cached


def _copy_to_container(container_name: str, host_path: Path, container_path: str) -> bool:
    """Copy a host file into a running container via lxc-attach stdin pipe."""
    try:
        with open(host_path, "rb") as f:
            proc = subprocess.run(
                ["lxc-attach", "-n", container_name, "--", "bash", "-c",
                 f"cat > {container_path} && chmod 644 {container_path}"],
                stdin=f, capture_output=True, timeout=120,
            )
            return proc.returncode == 0
    except Exception as e:
        logger.warning(f"_copy_to_container failed for {container_name}: {e}")
        return False


# ===== WAZUH AGENT INSTALLATION =====

def install_wazuh_agent(container_name: str, wazuh_manager: str, agent_group: str, 
                       version: str = "4.14.2", config_template_id: Optional[str] = None) -> Dict[str, Any]:
    """Install Wazuh agent in a container using a direct .deb download (cached)."""
    logger.info(f"Installing Wazuh agent {version} in container '{container_name}'")

    # The Wazuh .deb URL includes a patch suffix (-1); try the exact version first
    deb_name = f"wazuh-agent_{version}-1_amd64.deb"
    deb_url = f"https://packages.wazuh.com/4.x/apt/pool/main/w/wazuh-agent/{deb_name}"
    container_deb = f"/tmp/{deb_name}"

    with PerformanceTimer(f"Wazuh installation on {container_name}"):
        # Download .deb to host cache once, then copy into container
        try:
            cached = _ensure_cached(
                deb_name,
                ["wget", "-q", "-O", str(AGENT_CACHE_DIR / deb_name), deb_url],
                timeout=180,
            )
            if not _copy_to_container(container_name, cached, container_deb):
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

export WAZUH_MANAGER='{wazuh_manager}'
export WAZUH_AGENT_GROUP='{agent_group}'
export WAZUH_AGENT_NAME='{container_name}'
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

# ===== OSSEC AGENT INSTALLATION =====

def install_ossec_agent(container_name: str, ossec_server: str,
                       config_template_id: Optional[str] = None) -> Dict[str, Any]:
    """Install OSSEC agent in a container using the Atomicorp installer."""
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

# ===== OSSIM AGENT INSTALLATION =====

def install_ossim_agent(container_name: str, ossim_server: str,
                       config_template_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Install OSSIM/AlienVault agent in a container
    
    Args:
        container_name: Name of the container
        ossim_server: OSSIM server IP/hostname
        config_template_id: Optional config template to apply
    
    Returns:
        Dict with success status and output
    """
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

# ===== UTMSTACK AGENT INSTALLATION =====

def install_utmstack_agent(container_name: str, utmstack_server: str,
                           auth_key: str,
                           config_template_id: Optional[str] = None) -> Dict[str, Any]:
    """Install UTMstack agent in a container."""
    logger.info(f"Installing UTMstack agent in container '{container_name}'")

    binary_name = f"utmstack_agent_service_{utmstack_server}"
    binary_url = f"https://{utmstack_server}:9001/private/dependencies/agent/utmstack_agent_service"
    container_bin = "/opt/utmstack-linux-agent/utmstack_agent_service"

    with PerformanceTimer(f"UTMstack installation on {container_name}"):
        # Cache the binary on the host, then copy into the container
        copied = False
        try:
            cached = _ensure_cached(
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
            if _copy_to_container(container_name, cached, container_bin):
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

MANAGER_IP="{utmstack_server}"
AUTH_KEY="{auth_key}"

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

# ===== ELASTIC AGENT INSTALLATION =====

def install_elastic_agent(container_name: str, fleet_url: str,
                          enrollment_token: str,
                          version: str = "9.0.2",
                          config_template_id: Optional[str] = None) -> Dict[str, Any]:
    """Install Elastic Agent in a container via Fleet enrollment."""
    logger.info(f"Installing Elastic Agent in container '{container_name}'")

    deb_file = f"elastic-agent-{version}-amd64.deb"
    deb_url = f"https://artifacts.elastic.co/downloads/beats/elastic-agent/{deb_file}"
    container_deb = f"/tmp/{deb_file}"

    with PerformanceTimer(f"Elastic Agent installation on {container_name}"):
        # Download .deb to host cache once, then copy into container
        try:
            cached = _ensure_cached(
                deb_file,
                ["wget", "-q", "-O", str(AGENT_CACHE_DIR / deb_file), deb_url],
                timeout=180,
            )
            if not _copy_to_container(container_name, cached, container_deb):
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

        elastic_script = f"""#!/bin/bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

FLEET_URL="{fleet_url}"
ENROLLMENT_TOKEN="{enrollment_token}"

apt-get update -y
apt-get install -y curl wget
{download_block}
ELASTIC_AGENT_FLAVOR=servers dpkg -i "{container_deb}"
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

# ===== BATCH SIEM INSTALLATION =====

def install_siem_batch(container_names: List[str], siem_type: str, siem_server: str,
                      agent_group: str = "default", version: str = "4.14.2",
                      max_workers: int = 5) -> Dict[str, Dict[str, Any]]:
    """
    Install SIEM agents on multiple containers in parallel
    
    Args:
        container_names: List of container names
        siem_type: Type of SIEM (wazuh, ossec, ossim)
        siem_server: SIEM server IP/hostname
        agent_group: Agent group (for Wazuh)
        version: SIEM version (for Wazuh)
        max_workers: Maximum concurrent installations
    
    Returns:
        Dict mapping container names to installation results
    """
    results = {}
    
    logger.info(f"Installing {siem_type} on {len(container_names)} containers with {max_workers} workers")
    
    # Select installation function
    if siem_type == "wazuh":
        install_func = lambda name: install_wazuh_agent(name, siem_server, agent_group, version)
    elif siem_type == "ossec":
        install_func = lambda name: install_ossec_agent(name, siem_server)
    elif siem_type == "ossim":
        install_func = lambda name: install_ossim_agent(name, siem_server)
    elif siem_type == "utmstack":
        install_func = lambda name: install_utmstack_agent(name, siem_server, agent_group)
    elif siem_type == "elastic":
        install_func = lambda name: install_elastic_agent(name, siem_server, agent_group)
    else:
        raise ValueError(f"Unsupported SIEM type: {siem_type}")
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_name = {
            executor.submit(install_func, name): name
            for name in container_names
        }
        
        for future in as_completed(future_to_name):
            name = future_to_name[future]
            try:
                results[name] = future.result(timeout=900)  # 15 minute timeout
            except Exception as e:
                logger.error(f"Exception installing {siem_type} on {name}: {e}")
                results[name] = {
                    "success": False,
                    "error": str(e),
                    "stdout": "",
                    "stderr": str(e)
                }
    
    successful = sum(1 for r in results.values() if r.get("success"))
    logger.info(f"{siem_type} installation completed: {successful}/{len(container_names)} successful")
    
    return results

# ===== ATTACK SIMULATION ENGINE =====

class SimulationEngine:
    """Engine for generating attack simulations"""
    
    @staticmethod
    def generate_auth_bruteforce(container_name: str, duration: int, eps: int) -> Dict[str, Any]:
        """Generate authentication brute force logs"""
        script = f"""#!/bin/bash
END_TIME=$(($(date +%s) + {duration}))
COUNT=0

while [ $(date +%s) -lt $END_TIME ]; do
    for i in {{1..{eps}}}; do
        USERNAME="user$((RANDOM % 100))"
        IP="192.168.$((RANDOM % 255)).$((RANDOM % 255))"
        echo "$(date '+%b %d %H:%M:%S') $(hostname) sshd[$$]: Failed password for $USERNAME from $IP port $((RANDOM % 65535)) ssh2" >> /var/log/auth.log
        COUNT=$((COUNT + 1))
    done
    sleep 1
done

echo "Generated $COUNT auth bruteforce events"
"""
        return execute_in_container_shell(container_name, script, timeout=duration + 30)
    
    @staticmethod
    def generate_web_attacks(container_name: str, duration: int, eps: int) -> Dict[str, Any]:
        """Generate web attack logs"""
        attacks = [
            "GET /admin/../../../etc/passwd HTTP/1.1",
            "GET /index.php?id=1' OR '1'='1 HTTP/1.1",
            "POST /login.php HTTP/1.1' UNION SELECT * FROM users--",
            "GET /<script>alert(document.cookie)</script> HTTP/1.1",
            "GET /cmd.php?cmd=cat%20/etc/passwd HTTP/1.1"
        ]
        
        script = f"""#!/bin/bash
mkdir -p /var/log/apache2 /var/log/nginx
END_TIME=$(($(date +%s) + {duration}))
COUNT=0

ATTACKS=(
{chr(10).join(f'  "{attack}"' for attack in attacks)}
)

while [ $(date +%s) -lt $END_TIME ]; do
    for i in {{1..{eps}}}; do
        IP="192.168.$((RANDOM % 255)).$((RANDOM % 255))"
        ATTACK="${{ATTACKS[$RANDOM % ${{#ATTACKS[@]}}]}}"
        STATUS=$((400 + RANDOM % 100))
        echo "$IP - - [$(date '+%d/%b/%Y:%H:%M:%S %z')] \\"$ATTACK\\" $STATUS -" >> /var/log/apache2/access.log
        COUNT=$((COUNT + 1))
    done
    sleep 1
done

echo "Generated $COUNT web attack events"
"""
        return execute_in_container_shell(container_name, script, timeout=duration + 30)
    
    @staticmethod
    def generate_malware_beacon(container_name: str, duration: int, eps: int) -> Dict[str, Any]:
        """Generate malware C2 beacon logs"""
        c2_servers = [
            "185.220.100.240",
            "198.51.100.123",
            "203.0.113.45",
            "45.33.32.156"
        ]
        
        script = f"""#!/bin/bash
END_TIME=$(($(date +%s) + {duration}))
COUNT=0

C2_SERVERS=(
{chr(10).join(f'  "{server}"' for server in c2_servers)}
)

while [ $(date +%s) -lt $END_TIME ]; do
    for i in {{1..{eps}}}; do
        C2="${{C2_SERVERS[$RANDOM % ${{#C2_SERVERS[@]}}]}}"
        PORT=$((8000 + RANDOM % 2000))
        echo "$(date '+%b %d %H:%M:%S') $(hostname) MALWARE: Suspicious connection to $C2:$PORT (C2 Beacon)" >> /var/log/syslog
        COUNT=$((COUNT + 1))
    done
    sleep 1
done

echo "Generated $COUNT malware beacon events"
"""
        return execute_in_container_shell(container_name, script, timeout=duration + 30)
    
    @staticmethod
    def generate_lateral_movement(container_name: str, duration: int, eps: int) -> Dict[str, Any]:
        """Generate lateral movement logs"""
        script = f"""#!/bin/bash
END_TIME=$(($(date +%s) + {duration}))
COUNT=0

while [ $(date +%s) -lt $END_TIME ]; do
    for i in {{1..{eps}}}; do
        TARGET_IP="10.0.$((RANDOM % 255)).$((RANDOM % 255))"
        PORT=$((135 + RANDOM % 500))
        PROTOCOL=$((RANDOM % 2 == 0 ? "SMB" : "RDP"))
        echo "$(date '+%b %d %H:%M:%S') $(hostname) SECURITY: Lateral movement attempt to $TARGET_IP:$PORT using $PROTOCOL" >> /var/log/security.log
        COUNT=$((COUNT + 1))
    done
    sleep 1
done

echo "Generated $COUNT lateral movement events"
"""
        return execute_in_container_shell(container_name, script, timeout=duration + 30)
    
    @staticmethod
    def generate_privilege_escalation(container_name: str, duration: int, eps: int) -> Dict[str, Any]:
        """Generate privilege escalation logs"""
        script = f"""#!/bin/bash
END_TIME=$(($(date +%s) + {duration}))
COUNT=0

USERS=("www-data" "nginx" "apache" "nobody")
COMMANDS=("sudo su -" "sudo /bin/bash" "sudo chmod u+s /bin/bash" "sudo cat /etc/shadow")

while [ $(date +%s) -lt $END_TIME ]; do
    for i in {{1..{eps}}}; do
        USER="${{USERS[$RANDOM % ${{#USERS[@]}}]}}"
        CMD="${{COMMANDS[$RANDOM % ${{#COMMANDS[@]}}]}}"
        echo "$(date '+%b %d %H:%M:%S') $(hostname) sudo: $USER : user NOT in sudoers ; TTY=pts/$((RANDOM % 10)) ; PWD=/tmp ; USER=root ; COMMAND=$CMD" >> /var/log/auth.log
        COUNT=$((COUNT + 1))
    done
    sleep 1
done

echo "Generated $COUNT privilege escalation events"
"""
        return execute_in_container_shell(container_name, script, timeout=duration + 30)
    
    @staticmethod
    def generate_port_scan(container_name: str, duration: int, eps: int) -> Dict[str, Any]:
        """Generate port scan logs"""
        script = f"""#!/bin/bash
END_TIME=$(($(date +%s) + {duration}))
COUNT=0

while [ $(date +%s) -lt $END_TIME ]; do
    for i in {{1..{eps}}}; do
        SCANNER_IP="192.168.$((RANDOM % 255)).$((RANDOM % 255))"
        TARGET_PORT=$((1 + RANDOM % 65535))
        echo "$(date '+%b %d %H:%M:%S') $(hostname) kernel: [UFW BLOCK] IN=eth0 OUT= SRC=$SCANNER_IP DST=10.0.0.1 PROTO=TCP SPT=$((RANDOM % 65535)) DPT=$TARGET_PORT" >> /var/log/syslog
        COUNT=$((COUNT + 1))
    done
    sleep 1
done

echo "Generated $COUNT port scan events"
"""
        return execute_in_container_shell(container_name, script, timeout=duration + 30)

def get_simulation_generator(profile_id: str) -> Callable:
    """Get the appropriate simulation generator for a profile"""
    generators = {
        "auth_bruteforce": SimulationEngine.generate_auth_bruteforce,
        "web_attacks": SimulationEngine.generate_web_attacks,
        "malware_beacon": SimulationEngine.generate_malware_beacon,
        "lateral_movement": SimulationEngine.generate_lateral_movement,
        "privilege_escalation": SimulationEngine.generate_privilege_escalation,
        "port_scan": SimulationEngine.generate_port_scan,
    }
    
    return generators.get(profile_id, SimulationEngine.generate_auth_bruteforce)



# ===== ASYNC WAZUH INSTALLATION =====

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

# ===== CONTAINER LIFECYCLE HELPERS =====

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

# ===== LOG INJECTION UTILITIES =====

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
        operator = ">>" if append else ">"
        
        script = f"""
mkdir -p $(dirname {destination_path})
cat {operator} {destination_path} << 'EOFLOG'
{log_content}
EOFLOG
chmod 644 {destination_path}
echo "Injected $(wc -l < {destination_path}) lines to {destination_path}"
"""
        
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

# ===== RESOURCE MONITORING =====

def get_system_resources() -> Dict[str, Any]:
    """Get system resource information"""
    try:
        # CPU info
        cpu_count = os.cpu_count() or 1
        
        # Memory info
        with open('/proc/meminfo', 'r') as f:
            meminfo = f.read()
        mem_total = int(re.search(r'MemTotal:\s+(\d+)', meminfo).group(1)) // 1024  # MB
        mem_available = int(re.search(r'MemAvailable:\s+(\d+)', meminfo).group(1)) // 1024  # MB
        
        # Load average
        with open('/proc/loadavg', 'r') as f:
            load_avg = [float(x) for x in f.read().split()[:3]]
        
        # Disk info
        stat = os.statvfs('/')
        disk_total = (stat.f_blocks * stat.f_frsize) / (1024**3)  # GB
        disk_free = (stat.f_bavail * stat.f_frsize) / (1024**3)  # GB
        
        return {
            "cpu_count": cpu_count,
            "memory_total_mb": mem_total,
            "memory_available_mb": mem_available,
            "memory_used_percent": ((mem_total - mem_available) / mem_total * 100) if mem_total > 0 else 0,
            "load_average": load_avg,
            "disk_total_gb": disk_total,
            "disk_free_gb": disk_free,
            "disk_used_percent": ((disk_total - disk_free) / disk_total * 100) if disk_total > 0 else 0
        }
    except Exception as e:
        logger.error(f"Failed to get system resources: {e}")
        return {"error": str(e)}

# ===== HELPER FUNCTIONS =====

def format_bytes(bytes_value: int) -> str:
    """Format bytes to human-readable string"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_value < 1024.0:
            return f"{bytes_value:.2f}{unit}"
        bytes_value /= 1024.0
    return f"{bytes_value:.2f}PB"

def format_duration(seconds: float) -> str:
    """Format seconds to human-readable duration"""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        return f"{seconds/60:.1f}m"
    else:
        return f"{seconds/3600:.1f}h"