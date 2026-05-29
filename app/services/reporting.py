"""
Report generation — CSV, PDF with matplotlib/reportlab.

Will receive from main.py (Phase 4):
  - generate_report_csv
  - generate_report_pdf
  - normalize_dt
"""
from datetime import datetime
from pathlib import Path
from typing import Any, Dict


def normalize_dt(value: datetime) -> datetime:
    raise NotImplementedError("Phase 4: move from main.py")


def generate_report_csv(report_data: Dict[str, Any], report_file: Path) -> None:
    raise NotImplementedError("Phase 4: move from main.py")


def generate_report_pdf(
    report_data: Dict[str, Any],
    agent_status_counts: Dict[str, int],
    report_file: Path,
) -> None:
    raise NotImplementedError("Phase 4: move from main.py")
