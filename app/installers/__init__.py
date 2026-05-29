"""
SIEM agent installers — one module per SIEM type.

Will receive from utils.py (Phase 2):
  - install_siem_batch  (dispatcher, lives here)

Each sub-module owns a single install_*_agent function.
"""
from typing import Any, Dict, List


def install_siem_batch(
    container_names: List[str],
    siem_type: str,
    siem_server: str,
    agent_group: str = "default",
    version: str = "4.14.2",
    max_workers: int = 5,
) -> Dict[str, Dict[str, Any]]:
    raise NotImplementedError("Phase 2: move from utils.py")
