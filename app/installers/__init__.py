"""
SIEM agent installers — one module per SIEM type, plus the batch dispatcher.
"""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List

from app.installers.elastic import install_elastic_agent
from app.installers.ossec import install_ossec_agent
from app.installers.ossim import install_ossim_agent
from app.installers.utmstack import install_utmstack_agent
from app.installers.wazuh import install_wazuh_agent

logger = logging.getLogger(__name__)


def install_siem_batch(container_names: List[str], siem_type: str, siem_server: str,
                      agent_group: str = "default", version: str = "4.14.2",
                      max_workers: int = 5) -> Dict[str, Dict[str, Any]]:
    """
    Install SIEM agents on multiple containers in parallel
    
    Args:
        container_names: List of container names
        siem_type: Type of SIEM (wazuh, ossec, ossim)
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
    if siem_type == "wazuh":
        install_func = lambda name: install_wazuh_agent(name, siem_server, agent_group, version)
    elif siem_type == "ossec":
        install_func = lambda name: install_ossec_agent(name, siem_server)
    elif siem_type == "ossim":
        install_func = lambda name: install_ossim_agent(name, siem_server)
    elif siem_type == "utmstack":
        install_func = lambda name: install_utmstack_agent(name, siem_server, agent_group)
    elif siem_type == "elastic":
        install_func = lambda name: install_elastic_agent(name, siem_server, agent_group)
    else:
        raise ValueError(f"Unsupported SIEM type: {siem_type}")

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
