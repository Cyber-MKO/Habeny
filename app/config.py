"""
Centralized configuration — paths, constants, tunables.

Extracted from the module-level globals scattered across main.py.
"""
from multiprocessing import cpu_count
from pathlib import Path

DATA_DIR = Path("/var/lib/lxc-siem-platform")
CONFIGS_DIR = DATA_DIR / "configs"
REPORTS_DIR = DATA_DIR / "reports"
LOGS_DIR = DATA_DIR / "logs"
AGENTS_DIR = DATA_DIR / "agents"
DB_PATH = DATA_DIR / "platform.db"

MAX_WORKERS = cpu_count() * 2
