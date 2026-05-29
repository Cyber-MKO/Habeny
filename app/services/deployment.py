"""
Container deployment orchestration.

Will receive from main.py (Phase 4):
  - deploy_single_siem_agent
  - get_os_config
"""
from typing import Any, Dict, Optional


def deploy_single_siem_agent(
    agent_name: str,
    deployment_config: dict,
    agent_seq_id: Optional[int] = None,
) -> dict:
    raise NotImplementedError("Phase 4: move from main.py")


def get_os_config(os_type: str) -> dict:
    raise NotImplementedError("Phase 4: move from main.py")
