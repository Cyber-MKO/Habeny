"""
OSSEC agent installer (via Atomicorp repository).

Will receive from utils.py (Phase 2):
  - install_ossec_agent
"""
from typing import Any, Dict, Optional


def install_ossec_agent(
    container_name: str,
    ossec_server: str,
    config_template_id: Optional[str] = None,
) -> Dict[str, Any]:
    raise NotImplementedError("Phase 2: move from utils.py")
