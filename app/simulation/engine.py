"""
SimulationEngine and profile-to-generator dispatch.

Will receive from utils.py (Phase 3):
  - SimulationEngine          (class with static generator methods)
  - get_simulation_generator  (profile_id -> Callable dispatch)
"""
from typing import Any, Callable, Dict


class SimulationEngine:
    """Each static method generates a specific attack-profile log stream inside a container."""

    @staticmethod
    def generate_auth_bruteforce(container_name: str, duration: int, eps: int) -> Dict[str, Any]:
        raise NotImplementedError("Phase 3: move from utils.py")

    @staticmethod
    def generate_web_attacks(container_name: str, duration: int, eps: int) -> Dict[str, Any]:
        raise NotImplementedError("Phase 3: move from utils.py")

    @staticmethod
    def generate_malware_beacon(container_name: str, duration: int, eps: int) -> Dict[str, Any]:
        raise NotImplementedError("Phase 3: move from utils.py")

    @staticmethod
    def generate_lateral_movement(container_name: str, duration: int, eps: int) -> Dict[str, Any]:
        raise NotImplementedError("Phase 3: move from utils.py")

    @staticmethod
    def generate_privilege_escalation(container_name: str, duration: int, eps: int) -> Dict[str, Any]:
        raise NotImplementedError("Phase 3: move from utils.py")

    @staticmethod
    def generate_port_scan(container_name: str, duration: int, eps: int) -> Dict[str, Any]:
        raise NotImplementedError("Phase 3: move from utils.py")


def get_simulation_generator(profile_id: str) -> Callable:
    raise NotImplementedError("Phase 3: move from utils.py")
