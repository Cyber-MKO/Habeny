"""
All enums — container state, SIEM/OS types, simulation profiles, syslog devices, etc.
"""
from enum import Enum


class ContainerState(str, Enum):
    """LXC container states"""
    STOPPED = "STOPPED"
    RUNNING = "RUNNING"
    FROZEN = "FROZEN"
    STARTING = "STARTING"
    STOPPING = "STOPPING"
    ABORTING = "ABORTING"


class SIEMType(str, Enum):
    """Supported SIEM types"""
    NONE = "none"
    WAZUH = "wazuh"
    OSSEC = "ossec"
    OSSIM = "ossim"
    UTMSTACK = "utmstack"
    ELASTIC = "elastic"


class OSType(str, Enum):
    """Supported operating system types"""
    UBUNTU_22_04 = "ubuntu_22_04"
    UBUNTU_20_04 = "ubuntu_20_04"
    DEBIAN_11 = "debian_11"
    DEBIAN_10 = "debian_10"
    CENTOS_8 = "centos_8"


class ArchType(str, Enum):
    """Supported architectures"""
    AMD64 = "amd64"
    ARM64 = "arm64"
    ARMHF = "armhf"
    I386 = "i386"


class TemplateType(str, Enum):
    """LXC template types"""
    DOWNLOAD = "download"
    UBUNTU = "ubuntu"
    DEBIAN = "debian"
    ALPINE = "alpine"
    BUSYBOX = "busybox"


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


class SIEMConnectivityStatus(str, Enum):
    """SIEM connectivity status"""
    CONNECTED = "connected"
    PENDING = "pending"
    DISCONNECTED = "disconnected"
    ERROR = "error"
    NEVER_CONNECTED = "never_connected"


class SimulationStatus(str, Enum):
    """Simulation status"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"


class SimulationProfile(str, Enum):
    """Attack simulation profiles"""
    AUTH_BRUTEFORCE = "auth_bruteforce"
    WEB_ATTACKS = "web_attacks"
    MALWARE_BEACON = "malware_beacon"
    LATERAL_MOVEMENT = "lateral_movement"
    DATA_EXFILTRATION = "data_exfiltration"
    PRIVILEGE_ESCALATION = "privilege_escalation"
    PORT_SCAN = "port_scan"
    SQL_INJECTION = "sql_injection"
    XSS_ATTACK = "xss_attack"
    DDoS_ATTACK = "ddos_attack"


class LogType(str, Enum):
    """Log types for injection"""
    AUTH = "auth"
    WEB = "web"
    APPLICATION = "application"
    SYSTEM = "system"
    SECURITY = "security"
    CUSTOM = "custom"


class SyslogDeviceType(str, Enum):
    """Network device types for syslog simulation"""
    ROUTER = "router"
    SWITCH = "switch"
    FIREWALL = "firewall"
    IDS = "ids"
    MIXED = "mixed"
