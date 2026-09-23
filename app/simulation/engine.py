"""
SimulationEngine and profile-to-generator dispatch.
"""
from typing import Any, Callable, Dict

from app.core.shell import execute_in_container_shell


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
