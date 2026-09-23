"""
Shell command execution and container-attach wrappers.
"""
import logging
import os
import subprocess
import tempfile
import time
from functools import wraps
from typing import Any, Dict, List

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


def run_command(cmd: List[str], capture_output: bool = True, input_text: str = None,
                timeout: int = 300, env: Dict[str, str] = None) -> Dict[str, Any]:
    """Run a shell command and return a result dict with success, stdout, stderr, returncode."""
    try:
        process_env = os.environ.copy()
        if env:
            process_env.update(env)

        kwargs: Dict[str, Any] = {
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


@retry(max_attempts=3, delay=2.0)
def execute_in_container(container_name: str, command: str, env: Dict[str, str] = None,
                         timeout: int = 300) -> Dict[str, Any]:
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
        # Build command
        cmd = ["lxc-attach", "-n", container_name]

        # Add environment variables before --
        if env:
            for key, value in env.items():
                cmd.extend(["-v", f"{key}={value}"])

        # Add the actual command after --
        cmd.extend(["--", "bash", "-c", command])

        # Execute
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )

        return {
            "success": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "returncode": result.returncode
        }

    except subprocess.TimeoutExpired as e:
        return {
            "success": False,
            "stdout": e.stdout.decode() if e.stdout else "",
            "stderr": f"Command timeout after {timeout}s",
            "returncode": -1
        }
    except Exception as e:
        return {
            "success": False,
            "stdout": "",
            "stderr": str(e),
            "returncode": 1
        }


def execute_in_container_shell(container_name: str, command: str, env: Dict[str, str] = None,
                               timeout: int = 300) -> Dict[str, Any]:
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
        # Create a temporary script
        script_content = f"""#!/bin/bash
set -o pipefail
{command}
"""

        # Create temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
            f.write(script_content)
            script_path = f.name

        os.chmod(script_path, 0o755)

        # Prepare environment variables
        env_args = []
        if env:
            for key, value in env.items():
                env_args.extend(["-v", f"{key}={value}"])

        # Copy script to container
        container_script_path = f"/tmp/script_{os.path.basename(script_path)}"

        with open(script_path, 'r') as f:
            script_data = f.read()

        copy_cmd = ["lxc-attach", "-n", container_name, "--", "bash", "-c",
                   f"cat > {container_script_path} && chmod +x {container_script_path}"]

        copy_result = subprocess.run(
            copy_cmd,
            input=script_data,
            capture_output=True,
            text=True,
            timeout=30
        )

        if copy_result.returncode != 0:
            os.unlink(script_path)
            return {
                "success": False,
                "stdout": "",
                "stderr": f"Failed to copy script to container: {copy_result.stderr}",
                "returncode": copy_result.returncode
            }

        # Execute the script in container (env args before --)
        exec_cmd = ["lxc-attach", "-n", container_name] + env_args + ["--", "bash", container_script_path]

        result = subprocess.run(
            exec_cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )

        # Clean up
        os.unlink(script_path)
        subprocess.run(
            ["lxc-attach", "-n", container_name, "--", "rm", "-f", container_script_path],
            capture_output=True,
            timeout=10
        )

        return {
            "success": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "returncode": result.returncode
        }

    except subprocess.TimeoutExpired as e:
        return {
            "success": False,
            "stdout": e.stdout.decode() if e.stdout else "",
            "stderr": f"Script timeout after {timeout}s",
            "returncode": -1
        }
    except Exception as e:
        return {
            "success": False,
            "stdout": "",
            "stderr": str(e),
            "returncode": 1
        }
