"""
Shell command execution and container-attach wrappers.
"""
import logging
import os
import subprocess
import time
import uuid
from functools import wraps
from typing import Any

from app.core.lxc_backend import attach_run

logger = logging.getLogger(__name__)


def retry(max_attempts: int = 3, delay: float = 1.0, backoff: float = 2.0):
    """Retry decorator with exponential backoff"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            attempts = 0
            current_delay = delay

            while attempts < max_attempts:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    attempts += 1
                    if attempts >= max_attempts:
                        logger.error(f"Function {func.__name__} failed after {max_attempts} attempts: {e}")
                        raise
                    logger.warning(f"Attempt {attempts} failed for {func.__name__}: {e}. Retrying in {current_delay}s...")
                    time.sleep(current_delay)
                    current_delay *= backoff

        return wrapper
    return decorator


class PerformanceTimer:
    """Context manager for timing operations"""

    def __init__(self, operation_name: str, log_result: bool = True):
        self.operation_name = operation_name
        self.log_result = log_result
        self.start_time = None
        self.end_time = None

    def __enter__(self):
        self.start_time = time.time()
        logger.info(f"Starting: {self.operation_name}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end_time = time.time()
        elapsed = self.end_time - self.start_time
        if self.log_result:
            logger.info(f"Completed: {self.operation_name} in {elapsed:.2f}s")
        return False

    @property
    def elapsed(self) -> float:
        if self.end_time is not None and self.start_time is not None:
            return self.end_time - self.start_time
        return 0.0


def run_command(cmd: list[str], capture_output: bool = True, input_text: str = None,
                timeout: int = 300, env: dict[str, str] = None) -> dict[str, Any]:
    """Run a shell command and return a result dict with success, stdout, stderr, returncode."""
    try:
        process_env = os.environ.copy()
        if env:
            process_env.update(env)

        kwargs: dict[str, Any] = {
            "text": True, "check": True, "timeout": timeout, "env": process_env
        }
        if input_text is not None:
            kwargs["input"] = input_text
        if capture_output:
            kwargs["capture_output"] = True

        result = subprocess.run(cmd, **kwargs)

        if capture_output:
            return {
                "success": True,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
                "returncode": result.returncode
            }
        return {"success": True}
    except subprocess.TimeoutExpired as e:
        return {
            "success": False,
            "error": f"Command timeout after {timeout}s",
            "stdout": e.stdout.strip() if e.stdout else "",
            "stderr": e.stderr.strip() if e.stderr else "",
            "returncode": -1
        }
    except subprocess.CalledProcessError as e:
        return {
            "success": False,
            "error": str(e),
            "stdout": e.stdout.strip() if e.stdout else "",
            "stderr": e.stderr.strip() if e.stderr else "",
            "returncode": e.returncode
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "stdout": "",
            "stderr": "",
            "returncode": 1
        }


def _attach_result(result: dict[str, Any], timeout_msg: str) -> dict[str, Any]:
    if result.get("timed_out"):
        return {"success": False, "stdout": result["stdout"].strip(), "stderr": timeout_msg, "returncode": -1}
    return {
        "success": result["returncode"] == 0,
        "stdout": result["stdout"].strip(),
        "stderr": result["stderr"].strip(),
        "returncode": result["returncode"],
    }


@retry(max_attempts=3, delay=2.0)
def execute_in_container(container_name: str, command: str, env: dict[str, str] = None,
                         timeout: int = 300) -> dict[str, Any]:
    """
    Execute command in container using lxc-attach

    Args:
        container_name: Name of the container
        command: Command to execute
        env: Optional environment variables
        timeout: Command timeout in seconds

    Returns:
        Dict with success, stdout, stderr, returncode
    """
    try:
        result = attach_run(container_name, ["bash", "-c", command], env=env, timeout=timeout)
        return _attach_result(result, f"Command timeout after {timeout}s")
    except Exception as e:
        return {"success": False, "stdout": "", "stderr": str(e), "returncode": 1}


def execute_in_container_shell(container_name: str, command: str, env: dict[str, str] = None,
                               timeout: int = 300) -> dict[str, Any]:
    """
    Execute shell script in container with better error handling

    Args:
        container_name: Name of the container
        command: Shell script to execute
        env: Optional environment variables
        timeout: Script timeout in seconds

    Returns:
        Dict with success, stdout, stderr, returncode
    """
    try:
        script = f"#!/bin/bash\nset -o pipefail\n{command}\n"
        # Unique path inside the container; copy, run, clean up
        container_script_path = f"/tmp/script_{uuid.uuid4().hex}.sh"
        copy = attach_run(container_name, ["bash", "-c", 'cat > "$1" && chmod +x "$1"', "copy", container_script_path],
                          input_bytes=script.encode(), timeout=30)
        if copy["returncode"] != 0:
            return {
                "success": False,
                "stdout": "",
                "stderr": f"Failed to copy script to container: {copy['stderr'].strip()}",
                "returncode": copy["returncode"],
            }
        result = attach_run(container_name, ["bash", container_script_path], env=env, timeout=timeout)
        attach_run(container_name, ["rm", "-f", container_script_path], timeout=10)
        return _attach_result(result, f"Script timeout after {timeout}s")
    except Exception as e:
        return {"success": False, "stdout": "", "stderr": str(e), "returncode": 1}
