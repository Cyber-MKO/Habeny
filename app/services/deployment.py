"""
Container deployment — worker-process deploy of a single container and live progress tracking.
"""
import logging
import os
import queue
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from multiprocessing import Manager, cpu_count
from typing import Dict, List, Optional

import lxc

from app.config import DB_PATH
from app.core.container import parse_memory_limit, setup_agent_health_check
from app.core.network import configure_container_macvlan, get_host_interface
from app.installers.elastic import install_elastic_agent
from app.installers.ossec import install_ossec_agent
from app.installers.ossim import install_ossim_agent
from app.installers.utmstack import install_utmstack_agent
from app.installers.wazuh import install_wazuh_agent
from app.services.agent_info import write_agent_metadata
from app.state import MAX_TRACKED_DEPLOYMENTS, deployment_progress, deployment_progress_lock
from db import record_metric
from models import utc_now

logger = logging.getLogger(__name__)


def progress_start(deployment_id: str, count: int, siem_type: str):
    with deployment_progress_lock:
        deployment_progress[deployment_id] = {
            "deployment_id": deployment_id,
            "status": "running",
            "started_at": utc_now().isoformat(),
            "finished_at": None,
            "total": count,
            "completed": 0,
            "successful": 0,
            "failed": 0,
            "siem_type": siem_type,
            "containers": {},
            "events": [],
        }
        # Drop the oldest finished deployments so memory stays bounded
        finished = [k for k, v in deployment_progress.items() if v["status"] != "running"]
        for k in finished[:max(0, len(deployment_progress) - MAX_TRACKED_DEPLOYMENTS)]:
            deployment_progress.pop(k, None)


def progress_event(deployment_id: str, message: str, level: str = "info",
                    container: Optional[str] = None, status: Optional[str] = None,
                    error: Optional[str] = None):
    """Append an activity line and, if given, update the container's current step/status."""
    with deployment_progress_lock:
        job = deployment_progress.get(deployment_id)
        if not job:
            return
        now = utc_now().isoformat()
        job["events"].append({"timestamp": now, "level": level, "container": container, "message": message})
        if container:
            c = job["containers"].setdefault(container, {"name": container, "status": "pending", "step": "Queued"})
            c["step"] = message
            c["updated_at"] = now
            if status:
                c["status"] = status
            if error:
                c["error"] = error
            if status in ("success", "failed"):
                job["completed"] += 1
                job["successful" if status == "success" else "failed"] += 1


def progress_finish(deployment_id: str, status: str, message: str, level: str = "info"):
    progress_event(deployment_id, message, level=level)
    with deployment_progress_lock:
        job = deployment_progress.get(deployment_id)
        if job:
            job["status"] = status
            job["finished_at"] = utc_now().isoformat()


def _report_step(progress_queue, agent_name: str, message: str):
    """Send a step update from a deployment worker process back to the API process."""
    if progress_queue is None:
        return
    try:
        progress_queue.put_nowait((agent_name, message))
    except Exception:
        pass


def run_deployment_workers(deployment_id: str, agent_names: List[str], deployment_dict: dict,
                            agent_seq_ids: Dict[str, int]):
    """Deploy containers in worker processes, streaming their step updates into
    deployment_progress. Blocking; run it off the event loop."""
    results = []
    warnings = []
    with Manager() as mp_manager:
        progress_queue = mp_manager.Queue()

        def drain():
            while True:
                try:
                    name, message = progress_queue.get_nowait()
                except queue.Empty:
                    return
                progress_event(deployment_id, message, container=name, status="running")

        with ProcessPoolExecutor(max_workers=cpu_count()) as executor:
            future_to_name = {
                executor.submit(deploy_single_siem_agent, name, deployment_dict, agent_seq_ids[name], progress_queue): name
                for name in agent_names
            }
            pending = set(future_to_name)
            while pending:
                done, pending = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
                drain()
                for future in done:
                    agent_name = future_to_name[future]
                    try:
                        result = future.result()
                    except Exception as e:
                        logger.error(f"Exception deploying {agent_name}: {e}")
                        result = {"agent_name": agent_name, "success": False, "error": str(e)}
                    results.append(result)
                    if result["success"]:
                        progress_event(
                            deployment_id,
                            f"Deployed in {result.get('deploy_time_seconds', 0)}s"
                            + (f" ({result['ip_address']})" if result.get("ip_address") else ""),
                            level="success", container=agent_name, status="success",
                        )
                    else:
                        error = result.get("error") or (result.get("agent_installation") or {}).get("message") or "Unknown error"
                        warnings.append(f"Failed to deploy container {agent_name}: {error}")
                        progress_event(deployment_id, f"Failed: {error}", level="error",
                                        container=agent_name, status="failed", error=error)
    return results, warnings


def deploy_single_siem_agent(agent_name: str, deployment_config: dict, agent_seq_id: Optional[int] = None,
                             progress_queue=None) -> dict:
    """Deploy a single container with a SIEM agent"""
    deploy_start = time.time()
    try:
        logger.info(f"[{os.getpid()}] Deploying container: {agent_name}")
        _report_step(progress_queue, agent_name, "Checking for existing container")

        # Check if container exists
        if agent_name in lxc.list_containers():
            write_agent_metadata(
                agent_name,
                {
                    "agent_seq_id": agent_seq_id,
                    "lifecycle_status": "error",
                    "state": "EXISTS"
                }
            )
            return {
                "agent_name": agent_name,
                "agent_seq_id": agent_seq_id,
                "success": False,
                "error": "Container already exists"
            }

        # Create container
        container = lxc.Container(agent_name)

        # Map OS type to LXC parameters
        os_config = get_os_config(deployment_config["os_type"])
        _report_step(progress_queue, agent_name,
                     f"Creating container from {os_config['distro']} {os_config['release']} image")

        success = container.create(
            "download",
            0,
            {
                "dist": os_config["distro"],
                "release": os_config["release"],
                "arch": os_config["arch"]
            }
        )

        if not success:
            write_agent_metadata(
                agent_name,
                {
                    "agent_seq_id": agent_seq_id,
                    "lifecycle_status": "error",
                    "state": "CREATE_FAILED"
                }
            )
            return {
                "agent_name": agent_name,
                "agent_seq_id": agent_seq_id,
                "success": False,
                "error": "Container creation failed"
            }

        # Apply resource limits
        _report_step(progress_queue, agent_name, "Applying resource limits")
        if deployment_config.get("memory_limit"):
            container.set_cgroup_item("memory.max", parse_memory_limit(deployment_config["memory_limit"]))

        if deployment_config.get("cpu_shares"):
            container.set_cgroup_item("cpu.shares", str(deployment_config["cpu_shares"]))

        # OSSEC requires agent IPs to match what the manager sees. With the
        # default lxcbr0 (NAT), all containers share the host IP and OSSEC
        # rejects duplicates. Macvlan gives each container its own IP on the
        # host's physical network, solving the mismatch.
        siem_type = deployment_config.get("siem_type")
        if siem_type == "ossec":
            host_iface = get_host_interface()
            if host_iface:
                configure_container_macvlan(container, host_iface)
            else:
                logger.warning(
                    f"[{agent_name}] No wired interface for macvlan (WiFi-only host). "
                    f"Containers will use NAT. OSSEC manager needs <use_source_ip>no</use_source_ip> "
                    f"in its auth config, or agents must be manually keyed."
                )

        container.save_config()

        # Start container
        _report_step(progress_queue, agent_name, "Starting container")
        if not container.start():
            container.destroy()
            write_agent_metadata(
                agent_name,
                {
                    "agent_seq_id": agent_seq_id,
                    "lifecycle_status": "error",
                    "state": "START_FAILED"
                }
            )
            return {
                "agent_name": agent_name,
                "agent_seq_id": agent_seq_id,
                "success": False,
                "error": "Container start failed"
            }

        _report_step(progress_queue, agent_name, "Waiting for network")
        container.wait("RUNNING", 10)
        time.sleep(2)  # Wait for network

        # Install SIEM agent based on type
        install_result = None
        if siem_type != "none":
            _report_step(progress_queue, agent_name, f"Installing {siem_type} agent")

        if siem_type == "none":
            install_result = {"success": True, "stdout": "Bare container (no SIEM agent)"}
        elif siem_type == "wazuh":
            install_result = install_wazuh_agent(
                agent_name,
                deployment_config["siem_ip"],
                deployment_config["agent_group"],
                deployment_config.get("siem_version") or "4.14.2",
                deployment_config.get("config_template_id")
            )
        elif siem_type == "ossec":
            install_result = install_ossec_agent(
                agent_name,
                deployment_config["siem_ip"],
                deployment_config.get("config_template_id")
            )
        elif siem_type == "ossim":
            install_result = install_ossim_agent(
                agent_name,
                deployment_config["siem_ip"],
                deployment_config.get("config_template_id")
            )
        elif siem_type == "utmstack":
            install_result = install_utmstack_agent(
                agent_name,
                deployment_config["siem_ip"],
                deployment_config.get("siem_auth_key", ""),
                deployment_config.get("config_template_id")
            )
        elif siem_type == "elastic":
            install_result = install_elastic_agent(
                agent_name,
                deployment_config["siem_ip"],
                deployment_config.get("siem_auth_key", ""),
                deployment_config.get("siem_version") or "9.0.2",
                deployment_config.get("config_template_id")
            )
        else:
            container.stop()
            container.destroy()
            write_agent_metadata(
                agent_name,
                {
                    "agent_seq_id": agent_seq_id,
                    "lifecycle_status": "error",
                    "state": "UNSUPPORTED"
                }
            )
            return {
                "agent_name": agent_name,
                "agent_seq_id": agent_seq_id,
                "success": False,
                "error": f"Unsupported SIEM type: {siem_type}"
            }

        # Get container IP
        ips = container.get_ips() if container.running else []

        install_success = install_result.get("success", False)
        write_agent_metadata(
            agent_name,
            {
                "agent_seq_id": agent_seq_id,
                "siem_type": siem_type,
                "siem_ip": deployment_config.get("siem_ip"),
                "siem_version": deployment_config.get("siem_version"),
                "agent_group": deployment_config.get("agent_group"),
                "os_type": deployment_config.get("os_type"),
                "config_template_id": deployment_config.get("config_template_id"),
                "installation_success": install_success,
                "lifecycle_status": "running" if container.running else "stopped",
                "state": container.state,
                "init_pid": container.init_pid,
                "ip_addresses": ips
            }
        )
        _report_step(progress_queue, agent_name, "Setting up health check")
        try:
            health_setup = setup_agent_health_check(agent_name)
            if not health_setup.get("success", False):
                logger.warning(f"Health check setup failed for {agent_name}: {health_setup.get('stderr')}")
        except Exception as e:
            logger.warning(f"Health check setup error for {agent_name}: {e}")

        return {
            "agent_name": agent_name,
            "agent_seq_id": agent_seq_id,
            "container_id": agent_name,
            "success": install_success,
            "siem_type": siem_type,
            "siem_ip": deployment_config.get("siem_ip"),
            "agent_group": deployment_config.get("agent_group"),
            "os_type": deployment_config.get("os_type"),
            "ip_address": ips[0] if ips else None,
            "agent_installation": {
                "success": install_result["success"],
                "message": install_result.get("stdout", "")[:200] if install_result["success"] else install_result.get("stderr", "")
            },
            "deploy_time_seconds": round(time.time() - deploy_start, 2),
        }

        # Record per-container deployment timing
        try:
            record_metric(DB_PATH, "deployment", "container_deploy_time",
                         time.time() - deploy_start, siem_type)
            if install_success:
                record_metric(DB_PATH, "deployment", "container_success", 1, siem_type)
            else:
                record_metric(DB_PATH, "deployment", "container_failure", 1, siem_type)
        except Exception:
            pass

    except Exception as e:
        logger.error(f"Failed to deploy {agent_name}: {e}")
        return {
            "agent_name": agent_name,
            "success": False,
            "error": str(e)
        }


def get_os_config(os_type: str) -> dict:
    """Map OS type to LXC configuration"""
    os_configs = {
        "ubuntu_22_04": {"distro": "ubuntu", "release": "jammy", "arch": "amd64"},
        "ubuntu_20_04": {"distro": "ubuntu", "release": "focal", "arch": "amd64"},
        "debian_11": {"distro": "debian", "release": "bullseye", "arch": "amd64"},
    }
    return os_configs.get(os_type, os_configs["ubuntu_22_04"])
