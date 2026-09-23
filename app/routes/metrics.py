"""
Live metrics WebSocket and performance metrics endpoints.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import lxc
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.config import DB_PATH
from app.core.resources import get_system_resources
from app.db import get_metric_summary, query_metrics, record_metrics_batch
from app.models import APIResponse, utc_now
from app.services.agent_info import read_agent_metadata
from app.state import simulations_db

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws/metrics")
async def metrics_stream(websocket: WebSocket):
    """Push live platform metrics to connected React dashboards."""
    await websocket.accept()
    try:
        while True:
            try:
                containers = lxc.list_containers()
                running = sum(1 for n in containers if lxc.Container(n).running)
                by_status = {"running": running, "stopped": len(containers) - running}

                by_siem = {}
                for name in containers:
                    meta = read_agent_metadata(name)
                    stype = meta.get("siem_type") or "unknown"
                    by_siem[stype] = by_siem.get(stype, 0) + 1

                active_sims = len([s for s in simulations_db.values() if s.get("status") == "running"])
                total_events = sum(s.get("events_generated", 0) for s in simulations_db.values())
                running_sims_eps = sum(s.get("eps_target", 0) for s in simulations_db.values() if s.get("status") == "running")

                # System resources
                sys_res = get_system_resources()

                # Recent API latency (last 60s)
                try:
                    since = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
                    latency_summary = get_metric_summary(DB_PATH, "api_latency", "/agents/deploy", since)
                except Exception:
                    latency_summary = {}

                payload = {
                    "total_agents": len(containers),
                    "by_status": by_status,
                    "by_siem_type": by_siem,
                    "active_simulations": active_sims,
                    "total_events_generated": total_events,
                    "current_eps_target": running_sims_eps,
                    "system": {
                        "cpu_count": sys_res.get("cpu_count"),
                        "memory_used_percent": round(sys_res.get("memory_used_percent", 0), 1),
                        "memory_available_mb": sys_res.get("memory_available_mb"),
                        "disk_used_percent": round(sys_res.get("disk_used_percent", 0), 1),
                        "load_average": sys_res.get("load_average", []),
                    },
                    "deploy_latency": latency_summary,
                    "timestamp": utc_now().isoformat(),
                }

                # Persist system metrics snapshot for historical trending
                try:
                    record_metrics_batch(DB_PATH, [
                        ("system", "memory_used_percent", sys_res.get("memory_used_percent", 0), None),
                        ("system", "cpu_load_1m", sys_res.get("load_average", [0])[0] if sys_res.get("load_average") else 0, None),
                        ("system", "disk_used_percent", sys_res.get("disk_used_percent", 0), None),
                        ("system", "containers_running", running, None),
                    ])
                except Exception:
                    pass

                await websocket.send_json(payload)
            except Exception as e:
                logger.debug(f"Metrics collection error: {e}")

            # Wait for the next tick, but stop as soon as the client disconnects
            # (otherwise the loop outlives the connection)
            try:
                message = await asyncio.wait_for(websocket.receive(), timeout=5)
                if message["type"] == "websocket.disconnect":
                    break
            except asyncio.TimeoutError:
                pass
    except WebSocketDisconnect:
        pass
    except Exception:
        pass


@router.get("/metrics/benchmarks", response_model=APIResponse)
async def get_benchmarks(since: Optional[str] = Query(None, description="ISO timestamp to filter from")):
    """Get deployment and simulation performance benchmarks with percentiles"""
    try:
        deploy_time = get_metric_summary(DB_PATH, "deployment", "container_deploy_time", since)
        successes = get_metric_summary(DB_PATH, "deployment", "container_success", since)
        failures = get_metric_summary(DB_PATH, "deployment", "container_failure", since)

        total_deploys = (successes.get("cnt") or 0) + (failures.get("cnt") or 0)
        success_rate = round(((successes.get("cnt") or 0) / total_deploys * 100), 1) if total_deploys > 0 else 0

        api_latency = get_metric_summary(DB_PATH, "api_latency", "/agents/deploy", since)

        return APIResponse(success=True, message="Benchmarks retrieved", data={
            "deployment": {
                "total_deploys": total_deploys,
                "success_rate_percent": success_rate,
                "deploy_time_seconds": {
                    "avg": round(deploy_time.get("avg") or 0, 2),
                    "min": round(deploy_time.get("min") or 0, 2),
                    "max": round(deploy_time.get("max") or 0, 2),
                    "p50": round(deploy_time.get("p50") or 0, 2),
                    "p90": round(deploy_time.get("p90") or 0, 2),
                    "p99": round(deploy_time.get("p99") or 0, 2),
                },
            },
            "api_latency_ms": {
                "deploy_endpoint": {
                    "avg": round(api_latency.get("avg") or 0, 1),
                    "p50": round(api_latency.get("p50") or 0, 1),
                    "p90": round(api_latency.get("p90") or 0, 1),
                    "p99": round(api_latency.get("p99") or 0, 1),
                },
            },
            "simulations": {
                "total_events_generated": sum(s.get("events_generated", 0) for s in simulations_db.values()),
                "completed": len([s for s in simulations_db.values() if s.get("status") == "completed"]),
                "failed": len([s for s in simulations_db.values() if s.get("status") == "failed"]),
            },
        })
    except Exception as e:
        return APIResponse(success=False, message="Failed to get benchmarks", error=str(e))


@router.get("/metrics/history", response_model=APIResponse)
async def get_metrics_history(
    metric_type: str = Query(..., description="e.g. system, deployment, api_latency"),
    metric_name: Optional[str] = Query(None),
    since: Optional[str] = Query(None),
    limit: int = Query(500, ge=1, le=5000),
):
    """Get raw metrics history for charting"""
    try:
        rows = query_metrics(DB_PATH, metric_type, metric_name, since, limit)
        return APIResponse(success=True, message=f"Retrieved {len(rows)} data points", data={"metrics": rows})
    except Exception as e:
        return APIResponse(success=False, message="Failed to query metrics", error=str(e))


@router.get("/metrics/system", response_model=APIResponse)
async def get_system_metrics():
    """Get current system resource metrics"""
    try:
        res = get_system_resources()
        return APIResponse(success=True, message="System metrics retrieved", data=res)
    except Exception as e:
        return APIResponse(success=False, message="Failed to get system metrics", error=str(e))
