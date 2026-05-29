"""
Agent introspection — reading live container state and SIEM connectivity.

Will receive from main.py (Phase 4):
  - get_agent_info
  - detect_siem_type
  - check_siem_connectivity
  - read_agent_metadata, write_agent_metadata, delete_agent_metadata
"""
from typing import Any, Dict, Optional


def get_agent_info(container: Any, detailed: bool = False) -> dict:
    raise NotImplementedError("Phase 4: move from main.py")


def detect_siem_type(container_name: str) -> Optional[str]:
    raise NotImplementedError("Phase 4: move from main.py")


def check_siem_connectivity(container_name: str) -> dict:
    raise NotImplementedError("Phase 4: move from main.py")
