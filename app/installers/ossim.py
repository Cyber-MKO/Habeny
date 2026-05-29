"""
OSSIM/AlienVault agent installer.

Will receive from utils.py (Phase 2):
  - install_ossim_agent
"""
from typing import Any, Dict, Optional


def install_ossim_agent(
    container_name: str,
    ossim_server: str,
    config_template_id: Optional[str] = None,
) -> Dict[str, Any]:
    raise NotImplementedError("Phase 2: move from utils.py")
