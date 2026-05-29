"""
Simulation execution — attack profiles, custom EPS logs, syslog forwarding.

Will receive from main.py (Phase 4):
  - run_simulation
  - run_custom_log_simulation
  - run_syslog_simulation
  - select_agents_for_simulation
  - generate_simulation_events, get_simulation_script
  - _build_custom_log_script, _build_syslog_message, _send_syslog_message
  - SYSLOG_TEMPLATES
"""
from typing import Any, Dict, List


async def run_simulation(
    simulation_id: str,
    profile_id: str,
    agents: List[str],
    duration: int,
    eps_target: int,
) -> None:
    raise NotImplementedError("Phase 4: move from main.py")


async def run_custom_log_simulation(
    simulation_id: str,
    containers: List[str],
    config: Any,
) -> None:
    raise NotImplementedError("Phase 4: move from main.py")


def run_syslog_simulation(simulation_id: str, request: Any) -> None:
    raise NotImplementedError("Phase 4: move from main.py")
