"""
Shell command execution and container-attach wrappers.

Will receive from utils.py (Phase 1):
  - retry                       (decorator)
  - PerformanceTimer             (context manager)
  - run_command                  (subprocess wrapper)
  - execute_in_container         (lxc-attach single command)
  - execute_in_container_shell   (lxc-attach multi-line script)
"""
from typing import Any, Dict, List, Optional


def run_command(
    cmd: List[str],
    capture_output: bool = True,
    input_text: Optional[str] = None,
    timeout: int = 300,
    env: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    raise NotImplementedError("Phase 1: move from utils.py")


def execute_in_container(
    container_name: str,
    command: str,
    env: Optional[Dict[str, str]] = None,
    timeout: int = 300,
) -> Dict[str, Any]:
    raise NotImplementedError("Phase 1: move from utils.py")


def execute_in_container_shell(
    container_name: str,
    command: str,
    env: Optional[Dict[str, str]] = None,
    timeout: int = 300,
) -> Dict[str, Any]:
    raise NotImplementedError("Phase 1: move from utils.py")
