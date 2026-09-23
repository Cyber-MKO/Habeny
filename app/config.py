"""
Centralized configuration — paths, constants, tunables.
"""
import os
from multiprocessing import cpu_count
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = Path(os.environ.get("HABENY_DATA_DIR", "/var/lib/lxc-siem-platform"))
CONFIGS_DIR = DATA_DIR / "configs"
REPORTS_DIR = DATA_DIR / "reports"
LOGS_DIR = DATA_DIR / "logs"
AGENTS_DIR = DATA_DIR / "agents"
DB_PATH = DATA_DIR / "platform.db"

# Built React frontend (see frontend/vite.config.js build.outDir)
STATIC_DIR = ROOT_DIR / "static"

MAX_WORKERS = cpu_count() * 2

# Authentication
SESSION_COOKIE = "habeny_session"
SESSION_TTL_HOURS = int(os.environ.get("HABENY_SESSION_TTL_HOURS", "168"))  # 7 days

# Browser origins allowed to call the API cross-origin (comma-separated, exact
# "https://host:port" values). Empty (default): same-origin only.
CORS_ORIGINS = [o.strip().rstrip("/") for o in os.environ.get("HABENY_CORS_ORIGINS", "").split(",") if o.strip()]
if "*" in CORS_ORIGINS:
    raise RuntimeError("HABENY_CORS_ORIGINS must list exact origins; '*' is not allowed")
