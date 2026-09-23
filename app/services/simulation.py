"""
Simulation execution — attack profiles, custom EPS log streams and syslog forwarding.
"""
import asyncio
import json
import logging
import random
import socket
import time
from datetime import datetime
from typing import List

from fastapi.encoders import jsonable_encoder

from app.core.lxc_backend import lxc
from app.core.shell import execute_in_container, execute_in_container_shell
from app.models import AgentSelector, CustomLogSimulationRequest, SyslogSimulationRequest, utc_now
from app.services.activity import log_activity
from app.services.logs import escape_bash_single_quotes, escape_json_string
from app.state import simulations_db

logger = logging.getLogger(__name__)


def _build_custom_log_script(config: CustomLogSimulationRequest, simulation_id: str) -> str:
    extra_fields = jsonable_encoder(config.extra_fields or {})
    extra_fragment = ""
    if extra_fields:
        extra_json = json.dumps(extra_fields)
        if extra_json and extra_json != "{}":
            extra_fragment = f",{extra_json[1:-1]}"

    message_escaped = escape_json_string(config.message)
    script = f"""
FILE_PATH='{escape_bash_single_quotes(config.file_path)}'
MESSAGE_ESCAPED='{escape_bash_single_quotes(message_escaped)}'
SRC_IP='{escape_bash_single_quotes(config.src_ip)}'
DEST_IP='{escape_bash_single_quotes(config.dest_ip)}'
EXTRA_FRAGMENT='{escape_bash_single_quotes(extra_fragment)}'
SIM_ID='{escape_bash_single_quotes(simulation_id)}'
START_TIME='{escape_bash_single_quotes(config.start_time.isoformat() if config.start_time else "")}'
EPS={config.eps}
DURATION={config.duration}
SEQ_START={config.seq_start}
TOTAL=$((EPS * DURATION))

mkdir -p "$(dirname "$FILE_PATH")"

if [ -n "$START_TIME" ]; then
  START_EPOCH=$(date -u -d "$START_TIME" +%s 2>/dev/null || date +%s)
else
  START_EPOCH=$(date +%s)
fi

SEQ=$((SEQ_START - 1))
COUNT=0

for s in $(seq 1 "$DURATION"); do
  TS=$(date -u -d "@$((START_EPOCH + s - 1))" +%Y-%m-%dT%H:%M:%SZ)
  for i in $(seq 1 "$EPS"); do
    COUNT=$((COUNT + 1))
    SEQ=$((SEQ + 1))
    printf '{{"timestamp":"%s","date":"%s","eps":%s,"duration_seconds":%s,"src_ip":"%s","dest_ip":"%s","file_path":"%s","message":"%s","count":%s,"seq":%s,"simulation_id":"%s","total_count":%s%s}}\\n' \\
      "$TS" "$TS" "$EPS" "$DURATION" "$SRC_IP" "$DEST_IP" "$FILE_PATH" "$MESSAGE_ESCAPED" "$COUNT" "$SEQ" "$SIM_ID" "$TOTAL" "$EXTRA_FRAGMENT" >> "$FILE_PATH"
  done
  sleep 1
done

echo "Generated $COUNT custom events"
"""
    return script


def list_simulation_profiles() -> List[str]:
    """List available simulation profiles"""
    return [
        "auth_bruteforce",
        "web_attacks",
        "malware_beacon",
        "lateral_movement",
        "data_exfiltration",
        "privilege_escalation"
    ]


def select_agents_for_simulation(selector: AgentSelector) -> List[str]:
    """Select containers based on selector criteria"""
    all_containers = lxc.list_containers()
    selected = []

    # Filter by labels/tags (simplified - use metadata in production)
    for name in all_containers:
        container = lxc.Container(name)
        if not container.running:
            continue

        # Add filtering logic based on selector
        selected.append(name)

    if selector.count:
        selected = random.sample(selected, min(selector.count, len(selected)))

    return selected


async def run_simulation(simulation_id: str, profile_id: str, agents: List[str],
                        duration: int, eps_target: int):
    """Run simulation on selected containers"""
    try:
        logger.info(f"Starting simulation {simulation_id} on {len(agents)} containers")

        start_time = time.time()
        end_time = start_time + duration
        events_generated = 0

        while time.time() < end_time:
            # Generate events on containers
            for agent in agents:
                try:
                    result = generate_simulation_events(agent, profile_id, eps_target)
                    events_generated += result.get("events", 0)
                except Exception as e:
                    logger.error(f"Error generating events on {agent}: {e}")

            await asyncio.sleep(1)

            # Update simulation status
            if simulation_id in simulations_db:
                simulations_db[simulation_id]["events_generated"] = events_generated

        # Mark as completed
        if simulation_id in simulations_db:
            simulations_db[simulation_id]["status"] = "completed"
            simulations_db[simulation_id]["completed_at"] = utc_now().isoformat()
            simulations_db[simulation_id]["events_generated"] = events_generated

        log_activity("simulation_completed", {
            "simulation_id": simulation_id,
            "events_generated": events_generated
        })

        logger.info(f"Simulation {simulation_id} completed with {events_generated} events")

    except Exception as e:
        logger.error(f"Simulation {simulation_id} failed: {e}")
        if simulation_id in simulations_db:
            simulations_db[simulation_id]["status"] = "failed"
            simulations_db[simulation_id]["error"] = str(e)


async def run_custom_log_simulation(
    simulation_id: str,
    containers: List[str],
    config: CustomLogSimulationRequest
) -> None:
    try:
        timeout = config.duration + 60
        tasks = []
        for container_name in containers:
            script = _build_custom_log_script(config, simulation_id)
            tasks.append(asyncio.to_thread(
                execute_in_container_shell,
                container_name,
                script,
                None,
                timeout
            ))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        errors = []
        success_count = 0
        for container_name, result in zip(containers, results):
            if isinstance(result, Exception):
                errors.append({"container": container_name, "error": str(result)})
                continue
            if not result.get("success"):
                errors.append({"container": container_name, "error": result.get("stderr")})
                continue
            success_count += 1

        total_events = config.eps * config.duration * success_count

        if simulation_id in simulations_db:
            simulations_db[simulation_id]["events_generated"] = total_events
            simulations_db[simulation_id]["completed_at"] = utc_now().isoformat()
            simulations_db[simulation_id]["status"] = "completed" if success_count == len(containers) else "failed"
            if errors:
                simulations_db[simulation_id]["errors"] = errors

        log_activity("custom_log_simulation_completed", {
            "simulation_id": simulation_id,
            "successful_containers": success_count,
            "failed_containers": len(containers) - success_count,
            "events_generated": total_events
        })
    except Exception as e:
        logger.error(f"Custom log simulation {simulation_id} failed: {e}")
        if simulation_id in simulations_db:
            simulations_db[simulation_id]["status"] = "failed"
            simulations_db[simulation_id]["error"] = str(e)
        log_activity("custom_log_simulation_failed", {"simulation_id": simulation_id, "error": str(e)}, status="error")


SYSLOG_TEMPLATES = {
    "router": [
        "%LINK-5-CHANGED: Interface GigabitEthernet0/{iface} changed state to administratively down",
        "%LINEPROTO-5-UPDOWN: Line protocol on Interface GigabitEthernet0/{iface}, changed state to down",
        "%SYS-5-CONFIG_I: Configured from console by admin on vty0 ({device_ip})",
        "%OSPF-5-ADJCHG: Process 1, Nbr {peer_ip} on GigabitEthernet0/{iface} from FULL to DOWN, Neighbor Down: Dead timer expired",
        "%SEC_LOGIN-5-LOGIN_SUCCESS: Login successful [user: admin] [Source: {src_ip}] [localport: 22] at {timestamp}"
    ],
    "switch": [
        "%LINK-3-UPDOWN: Interface FastEthernet0/{iface}, changed state to up",
        "%SPANTREE-6-PORTBLK: Port Fa0/{iface} blocked by spanning tree.",
        "%MACFLAP_NOTIF: Host {mac} in vlan {vlan} is flapping between port Fa0/{iface} and port Fa0/{iface_alt}",
        "%DHCP_SNOOPING-5-DHCP_SNOOPING_NONZERO_GIADDR: DHCP_SNOOPING drop message with non-zero giaddr from interface Fa0/{iface}",
        "%AUTHPRIV-6-SYSTEM_MSG: AAA authorization succeeded for user admin - shell"
    ],
    "firewall": [
        "%ASA-6-302013: Built inbound TCP connection {conn} for inside:{src_ip}/{src_port} ({src_ip}/{src_port}) to outside:{dst_ip}/80",
        "%ASA-6-302014: Teardown TCP connection {conn} for inside:{src_ip}/{src_port} to outside:{dst_ip}/80 duration 0:{min}:{sec} bytes {bytes}",
        "%ASA-4-106023: Deny tcp src outside:{dst_ip}/{dst_port} dst inside:{src_ip}/22 by access-group \"OUTSIDE_IN\" [0x0, 0x0]",
        "%ASA-5-111008: User 'admin' executed the 'enable' command.",
        "%ASA-6-305011: Built dynamic UDP translation from inside:{src_ip}/{src_port} to outside:{dst_ip}/{dst_port}"
    ],
    "ids": [
        "%ET NETBIOS DCERPC ISystemActivator SMB named pipe access attempt {sig}",
        "%ET TROJAN Possible Metasploit Payload common.ports.dstport {sig}",
        "%GPL ATTACK_RESPONSE id check returned root {sig}",
        "%ET SCAN Potential SSH Scan {sig}",
        "%ET WEB_CLIENT Microsoft Internet Explorer invalid MIME type attempt {sig}"
    ]
}


def _select_syslog_template(device_type: str) -> str:
    return random.choice(SYSLOG_TEMPLATES.get(device_type, SYSLOG_TEMPLATES["router"]))


def _build_syslog_message(device_name: str, device_ip: str, device_type: str, facility: int) -> str:
    timestamp = datetime.now().strftime("%b %d %H:%M:%S")
    severity = random.choices(
        [0, 1, 2, 3, 4, 5, 6, 7],
        weights=[0.1, 0.5, 1, 2, 5, 10, 70, 11.4]
    )[0]
    pri = f"<{facility * 8 + severity}>"
    template = _select_syslog_template(device_type)
    payload = template.format(
        iface=random.randint(1, 24),
        iface_alt=random.randint(1, 24),
        device_ip=device_ip,
        peer_ip=f"{random.randint(1,254)}.{random.randint(1,254)}.{random.randint(1,254)}.{random.randint(1,254)}",
        src_ip=f"{random.randint(10,250)}.{random.randint(10,250)}.{random.randint(10,250)}.{random.randint(10,250)}",
        dst_ip=f"{random.randint(1,254)}.{random.randint(1,254)}.{random.randint(1,254)}.{random.randint(1,254)}",
        src_port=random.randint(1024, 65535),
        dst_port=random.randint(1024, 65535),
        conn=random.randint(1000, 9999),
        min=random.randint(0, 59),
        sec=random.randint(0, 59),
        bytes=random.randint(100, 99999),
        vlan=random.randint(1, 100),
        mac=":".join(f"{random.randint(0,255):02x}" for _ in range(6)),
        sig=random.randint(1000, 9999),
        timestamp=timestamp
    )
    header = f"{timestamp} {device_name}"
    return f"{pri}{header}: {payload}"


def _send_syslog_message(target_ip: str, target_port: int, protocol: str, message: str) -> bool:
    try:
        if protocol == "tcp":
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            sock.connect((target_ip, target_port))
            sock.sendall(message.encode("utf-8") + b"\n")
            sock.close()
        else:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.sendto(message.encode("utf-8"), (target_ip, target_port))
            sock.close()
        return True
    except Exception:
        return False


def run_syslog_simulation(simulation_id: str, request: SyslogSimulationRequest) -> None:
    try:
        device_types = ["router", "switch", "firewall", "ids"]
        device_type_value = request.device_type.value if hasattr(request.device_type, "value") else request.device_type
        if device_type_value != "mixed":
            device_types = [device_type_value]

        devices = []
        for idx in range(request.device_count):
            device_type = device_types[idx % len(device_types)]
            device_name = f"{request.device_name_prefix}-{idx + 1:02d}"
            device_ip = f"10.0.{(idx % 254) + 1}.{(idx % 250) + 1}"
            devices.append((device_name, device_ip, device_type))

        total_sent = 0
        total_failed = 0
        protocol = request.protocol.value if hasattr(request.protocol, "value") else request.protocol
        per_device_base = request.eps // request.device_count
        remainder = request.eps % request.device_count

        for second in range(request.duration):
            status = simulations_db.get(simulation_id, {}).get("status")
            if status != "running":
                break
            for index, (device_name, device_ip, device_type) in enumerate(devices):
                count = per_device_base + (1 if index < remainder else 0)
                for _ in range(count):
                    message = _build_syslog_message(device_name, device_ip, device_type, request.facility)
                    if _send_syslog_message(request.target_ip, request.target_port, protocol, message):
                        total_sent += 1
                    else:
                        total_failed += 1
            time.sleep(1)

        simulation = simulations_db.get(simulation_id)
        if simulation:
            simulation["events_generated"] = total_sent
            simulation["completed_at"] = utc_now().isoformat()
            if simulation.get("status") == "running":
                simulation["status"] = "completed" if total_sent > 0 else "failed"
            simulation["messages_failed"] = total_failed

        log_activity("syslog_simulation_completed", {
            "simulation_id": simulation_id,
            "messages_sent": total_sent,
            "messages_failed": total_failed
        })
    except Exception as e:
        logger.error(f"Syslog simulation {simulation_id} failed: {e}")
        if simulation_id in simulations_db:
            simulations_db[simulation_id]["status"] = "failed"
            simulations_db[simulation_id]["error"] = str(e)
        log_activity("syslog_simulation_failed", {"simulation_id": simulation_id, "error": str(e)}, status="error")


def generate_simulation_events(agent_name: str, profile_id: str, eps_target: int) -> dict:
    """Generate simulation events on a container"""
    try:
        script = get_simulation_script(profile_id, eps_target)
        result = execute_in_container(agent_name, script, timeout=10)

        return {
            "success": result["success"],
            "events": eps_target  # Simplified
        }
    except Exception as e:
        logger.error(f"Failed to generate events on {agent_name}: {e}")
        return {"success": False, "events": 0}


def get_simulation_script(profile_id: str, eps_target: int) -> str:
    """Get simulation script for a profile"""
    scripts = {
        "auth_bruteforce": f"""
            for i in {{1..{eps_target}}}; do
                echo "$(date) sshd[$$]: Failed password for invalid user admin from 192.168.1.100 port 22 ssh2" >> /var/log/auth.log
            done
        """,
        "web_attacks": f"""
            for i in {{1..{eps_target}}}; do
                echo '$(date) 192.168.1.100 - - [$(date)] "GET /admin/../../../etc/passwd HTTP/1.1" 404 -' >> /var/log/apache2/access.log
            done
        """,
        "malware_beacon": f"""
            for i in {{1..{eps_target}}}; do
                echo "$(date) MALWARE: Beacon to C2 server 185.220.100.240:443" >> /var/log/syslog
            done
        """
    }

    return scripts.get(profile_id, "echo 'Unknown profile'")
