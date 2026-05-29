"""
UTMstack agent installer.

Will receive from utils.py:
  - install_utmstack_agent
"""
from typing import Any, Dict, Optional


def install_utmstack_agent(
    container_name: str,
    utmstack_server: str,
    auth_key: str,
    config_template_id: Optional[str] = None,
) -> Dict[str, Any]:
    raise NotImplementedError("Move from utils.py")
