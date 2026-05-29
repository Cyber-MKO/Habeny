"""
Wazuh agent installer.

Will receive from utils.py (Phase 2):
  - install_wazuh_agent
  - install_wazuh_on_create  (async background task)
"""
from typing import Any, Dict, Optional


def install_wazuh_agent(
    container_name: str,
    wazuh_manager: str,
    agent_group: str,
    version: str = "4.14.2",
    config_template_id: Optional[str] = None,
) -> Dict[str, Any]:
    raise NotImplementedError("Phase 2: move from utils.py")


async def install_wazuh_on_create(
    container_name: str,
    wazuh_manager: str,
    agent_group: str,
    version: str,
) -> None:
    raise NotImplementedError("Phase 2: move from utils.py")
