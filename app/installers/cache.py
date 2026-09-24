"""
Host-side cache of downloaded agent packages, shared by the installers.
"""
import logging
import threading
from pathlib import Path

from app.config import DATA_DIR
from app.core.lxc_backend import attach_run
from app.core.shell import run_command

logger = logging.getLogger(__name__)


AGENT_CACHE_DIR = DATA_DIR / "agent-cache"
AGENT_CACHE_DIR.mkdir(parents=True, exist_ok=True)

_cache_lock = threading.Lock()


def ensure_cached(filename: str, download_cmd: list[str], timeout: int = 120) -> Path:
    """Download a file to the host cache if it doesn't already exist.

    Thread-safe: concurrent containers wait for the first download to finish
    rather than downloading in parallel.
    Returns the path to the cached file.
    """
    cached = AGENT_CACHE_DIR / filename
    with _cache_lock:
        if cached.exists() and cached.stat().st_size > 0:
            logger.info(f"Agent cache hit: {filename}")
            return cached
        logger.info(f"Agent cache miss — downloading {filename}")
        result = run_command(download_cmd, timeout=timeout)
        if not result["success"]:
            raise RuntimeError(f"Failed to download {filename}: {result.get('error') or result.get('stderr')}")
        if not cached.exists():
            raise RuntimeError(f"Download command succeeded but {cached} not found")
        logger.info(f"Cached {filename} ({cached.stat().st_size} bytes)")
    return cached


def copy_to_container(container_name: str, host_path: Path, container_path: str) -> bool:
    """Copy a host file into a running container via lxc-attach stdin pipe."""
    try:
        data = Path(host_path).read_bytes()
        result = attach_run(container_name, ["bash", "-c", 'cat > "$1" && chmod 644 "$1"', "copy", container_path],
                            input_bytes=data, timeout=120)
        return result["returncode"] == 0
    except Exception as e:
        logger.warning(f"copy_to_container failed for {container_name}: {e}")
        return False
