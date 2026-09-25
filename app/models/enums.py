"""
All enums — SIEM/OS types, simulation profiles, syslog devices, etc.
"""
from enum import Enum


class SIEMType(str, Enum):
    """Supported SIEM types"""
    NONE = "none"
    WAZUH = "wazuh"
    OSSEC = "ossec"
    UTMSTACK = "utmstack"
    ELASTIC = "elastic"


class OSType(str, Enum):
    """Container images (app/core/os_images.py has one for each)"""
    UBUNTU_22_04 = "ubuntu_22_04"
    UBUNTU_24_04 = "ubuntu_24_04"
    DEBIAN_12 = "debian_12"


class ParallelMode(str, Enum):
    """Parallel execution modes"""
    SEQUENTIAL = "sequential"
    THREADING = "threading"
    MULTIPROCESSING = "multiprocessing"


class SyslogProtocol(str, Enum):
    """Syslog transport protocols"""
    UDP = "udp"
    TCP = "tcp"


class AgentLifecycleStatus(str, Enum):
    """Container lifecycle status"""
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"
    STARTING = "starting"
    STOPPING = "stopping"


class SimulationProfile(str, Enum):
    """Attack simulation profiles"""
    AUTH_BRUTEFORCE = "auth_bruteforce"
    WEB_ATTACKS = "web_attacks"
    MALWARE_BEACON = "malware_beacon"
    LATERAL_MOVEMENT = "lateral_movement"
    DATA_EXFILTRATION = "data_exfiltration"
    PRIVILEGE_ESCALATION = "privilege_escalation"


class SyslogDeviceType(str, Enum):
    """Network device types for syslog simulation"""
    ROUTER = "router"
    SWITCH = "switch"
    FIREWALL = "firewall"
    IDS = "ids"
    MIXED = "mixed"
