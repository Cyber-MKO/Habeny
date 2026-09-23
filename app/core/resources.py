"""
Host resource monitoring and formatting helpers.
"""
import logging
import os
import re
from typing import Any, Dict

logger = logging.getLogger(__name__)


def get_system_resources() -> Dict[str, Any]:
    """Get system resource information"""
    try:
        # CPU info
        cpu_count = os.cpu_count() or 1

        # Memory info
        with open('/proc/meminfo', 'r') as f:
            meminfo = f.read()
        mem_total = int(re.search(r'MemTotal:\s+(\d+)', meminfo).group(1)) // 1024  # MB
        mem_available = int(re.search(r'MemAvailable:\s+(\d+)', meminfo).group(1)) // 1024  # MB

        # Load average
        with open('/proc/loadavg', 'r') as f:
            load_avg = [float(x) for x in f.read().split()[:3]]

        # Disk info
        stat = os.statvfs('/')
        disk_total = (stat.f_blocks * stat.f_frsize) / (1024**3)  # GB
        disk_free = (stat.f_bavail * stat.f_frsize) / (1024**3)  # GB

        return {
            "cpu_count": cpu_count,
            "memory_total_mb": mem_total,
            "memory_available_mb": mem_available,
            "memory_used_percent": ((mem_total - mem_available) / mem_total * 100) if mem_total > 0 else 0,
            "load_average": load_avg,
            "disk_total_gb": disk_total,
            "disk_free_gb": disk_free,
            "disk_used_percent": ((disk_total - disk_free) / disk_total * 100) if disk_total > 0 else 0
        }
    except Exception as e:
        logger.error(f"Failed to get system resources: {e}")
        return {"error": str(e)}


def format_bytes(bytes_value: int) -> str:
    """Format bytes to human-readable string"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_value < 1024.0:
            return f"{bytes_value:.2f}{unit}"
        bytes_value /= 1024.0
    return f"{bytes_value:.2f}PB"


def format_duration(seconds: float) -> str:
    """Format seconds to human-readable duration"""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        return f"{seconds/60:.1f}m"
    else:
        return f"{seconds/3600:.1f}h"
