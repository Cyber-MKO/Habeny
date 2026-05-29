"""
Activity logging — write/read JSONL activity log files.

Will receive from main.py (Phase 4):
  - log_activity
  - read_activity_logs_from_files
"""
from typing import Any, Dict, List, Optional


def log_activity(action: str, details: Dict[str, Any], status: str = "success") -> None:
    raise NotImplementedError("Phase 4: move from main.py")


def read_activity_logs_from_files(action: Optional[str] = None) -> List[Dict[str, Any]]:
    raise NotImplementedError("Phase 4: move from main.py")
