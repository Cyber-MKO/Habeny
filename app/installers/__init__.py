"""
SIEM agent installers — one module per SIEM type, plus the batch dispatcher.
"""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from app.installers.elastic import install_elastic_agent
from app.installers.ossec import install_ossec_agent
from app.installers.utmstack import install_utmstack_agent
from app.installers.wazuh import install_wazuh_agent

logger = logging.getLogger(__name__)


def install_siem_batch(container_names: list[str], siem_type: str, siem_server: str,
                      agent_group: str = "default", version: str = "4.14.2",
                      max_workers: int = 5) -> dict[str, dict[str, Any]]:
    """
    Install SIEM agents on multiple containers in parallel

    Args:
        container_names: List of container names
        siem_type: Type of SIEM (wazuh, ossec, utmstack, elastic)
        siem_server: SIEM server IP/hostname
        agent_group: Agent group (for Wazuh)
        version: SIEM version (for Wazuh)
        max_workers: Maximum concurrent installations

    Returns:
        Dict mapping container names to installation results
    """
    results = {}

    logger.info(f"Installing {siem_type} on {len(container_names)} containers with {max_workers} workers")

    # Select installation function
    installers = {
        "wazuh": lambda name: install_wazuh_agent(name, siem_server, agent_group, version),
        "ossec": lambda name: install_ossec_agent(name, siem_server),
        "utmstack": lambda name: install_utmstack_agent(name, siem_server, agent_group),
        "elastic": lambda name: install_elastic_agent(name, siem_server, agent_group),
    }
    if siem_type not in installers:
        raise ValueError(f"Unsupported SIEM type: {siem_type}")
    install_func = installers[siem_type]

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_name = {
            executor.submit(install_func, name): name
            for name in container_names
        }

        for future in as_completed(future_to_name):
            name = future_to_name[future]
            try:
                results[name] = future.result(timeout=900)  # 15 minute timeout
            except Exception as e:
                logger.error(f"Exception installing {siem_type} on {name}: {e}")
                results[name] = {
                    "success": False,
                    "error": str(e),
                    "stdout": "",
                    "stderr": str(e)
                }

    successful = sum(1 for r in results.values() if r.get("success"))
    logger.info(f"{siem_type} installation completed: {successful}/{len(container_names)} successful")

    return results
