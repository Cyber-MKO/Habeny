"""
Elastic Agent installer (Fleet enrollment).

Will receive from utils.py:
  - install_elastic_agent
"""
from typing import Any, Dict, Optional


def install_elastic_agent(
    container_name: str,
    fleet_url: str,
    enrollment_token: str,
    version: str = "9.0.2",
    config_template_id: Optional[str] = None,
) -> Dict[str, Any]:
    raise NotImplementedError("Move from utils.py")
