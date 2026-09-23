"""
Benchmark scenarios, runs and comparisons.
"""
import uuid
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

import app.services.benchmarks as bm_engine
from app.models import APIResponse, BenchmarkCompareRequest, BenchmarkStartRequest
from app.services.activity import log_activity

router = APIRouter()


@router.get("/benchmarks/scenarios", response_model=APIResponse)
async def list_benchmark_scenarios():
    """List available benchmark scenarios"""
    scenarios = [{"id": s["id"], "name": s["name"], "description": s["description"],
                  "phases": len(s["phases"]), "total_agents": sum(p.get("agents", 0) for p in s["phases"])}
                 for s in bm_engine.SCENARIOS.values()]
    return APIResponse(success=True, message="Scenarios retrieved", data={"scenarios": scenarios})


@router.post("/benchmarks/start", response_model=APIResponse)
async def start_benchmark(request: BenchmarkStartRequest,
                          background_tasks: BackgroundTasks):
    """Start a benchmark execution"""
    try:
        scenario_id = request.scenario_id
        if scenario_id not in bm_engine.SCENARIOS:
            raise HTTPException(status_code=400, detail=f"Unknown scenario: {scenario_id}")
        benchmark_id = str(uuid.uuid4())
        cfg = {k: v for k, v in request.dict().items() if v is not None}
        if request.name:
            cfg["name"] = request.name

        background_tasks.add_task(bm_engine.run_benchmark, benchmark_id, scenario_id, cfg)
        log_activity("benchmark_started", {"benchmark_id": benchmark_id, "scenario": scenario_id})

        return APIResponse(success=True, message=f"Benchmark {benchmark_id[:8]} started",
                          data={"benchmark_id": benchmark_id, "scenario_id": scenario_id})
    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(success=False, message="Failed to start benchmark", error=str(e))


@router.post("/benchmarks/{benchmark_id}/stop", response_model=APIResponse)
async def stop_benchmark(benchmark_id: str):
    """Stop a running benchmark"""
    if benchmark_id in bm_engine.active_benchmarks:
        bm_engine.active_benchmarks[benchmark_id]["status"] = "stopped"
        return APIResponse(success=True, message="Benchmark stop requested")
    # If not in memory but still marked running in DB, it's stale — abort it
    bm = bm_engine.get_benchmark(benchmark_id)
    if bm and bm["status"] == "running":
        bm_engine._save_benchmark({**bm, "status": "aborted", "completed_at": bm_engine._now()})
        return APIResponse(success=True, message="Stale benchmark marked as aborted")
    return APIResponse(success=False, message="Benchmark not found or not running")


@router.post("/benchmarks/cleanup", response_model=APIResponse)
async def cleanup_benchmarks():
    """Mark all stale 'running' benchmarks as aborted"""
    cleaned = bm_engine.cleanup_stale_benchmarks()
    return APIResponse(success=True, message=f"Cleaned up {cleaned} stale benchmark(s)",
                      data={"cleaned": cleaned})


@router.get("/benchmarks", response_model=APIResponse)
async def list_benchmarks_endpoint():
    """List all benchmarks"""
    benchmarks = bm_engine.list_benchmarks()
    return APIResponse(success=True, message=f"Retrieved {len(benchmarks)} benchmarks",
                      data={"benchmarks": benchmarks, "total": len(benchmarks)})


@router.get("/benchmarks/{benchmark_id}", response_model=APIResponse)
async def get_benchmark_detail(benchmark_id: str):
    """Get detailed benchmark results"""
    bm = bm_engine.get_benchmark(benchmark_id)
    if not bm:
        raise HTTPException(status_code=404, detail="Benchmark not found")
    # Merge live data if running
    if benchmark_id in bm_engine.active_benchmarks:
        bm["live"] = bm_engine.active_benchmarks[benchmark_id].get("results", {}).get("live")
    return APIResponse(success=True, message="Benchmark retrieved", data=bm)


@router.get("/benchmarks/{benchmark_id}/metrics", response_model=APIResponse)
async def get_benchmark_metrics_endpoint(benchmark_id: str,
                                         category: Optional[str] = None,
                                         limit: int = Query(1000, ge=1, le=10000)):
    """Get time-series metrics for a benchmark"""
    metrics = bm_engine.get_benchmark_metrics(benchmark_id, category, limit)
    return APIResponse(success=True, message=f"Retrieved {len(metrics)} data points",
                      data={"metrics": metrics})


@router.get("/benchmarks/{benchmark_id}/bottlenecks", response_model=APIResponse)
async def get_benchmark_bottlenecks_endpoint(benchmark_id: str):
    """Get detected bottlenecks for a benchmark"""
    bottlenecks = bm_engine.get_benchmark_bottlenecks(benchmark_id)
    return APIResponse(success=True, message=f"Retrieved {len(bottlenecks)} bottlenecks",
                      data={"bottlenecks": bottlenecks})


@router.post("/benchmarks/compare", response_model=APIResponse)
async def compare_benchmarks_endpoint(request: BenchmarkCompareRequest):
    """Compare multiple benchmarks side-by-side"""
    result = bm_engine.compare_benchmarks(request.benchmark_ids)
    if "error" in result:
        return APIResponse(success=False, message=result["error"])
    return APIResponse(success=True, message="Comparison complete", data=result)
