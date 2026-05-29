"""
System resource monitoring.

Will receive from utils.py (Phase 1):
  - get_system_resources
  - format_bytes
  - format_duration
"""
from typing import Any, Dict


def get_system_resources() -> Dict[str, Any]:
    raise NotImplementedError("Phase 1: move from utils.py")


def format_bytes(bytes_value: int) -> str:
    raise NotImplementedError("Phase 1: move from utils.py")


def format_duration(seconds: float) -> str:
    raise NotImplementedError("Phase 1: move from utils.py")
