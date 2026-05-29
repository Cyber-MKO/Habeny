"""
Benchmark execution framework.

Orchestrates multi-phase benchmark scenarios, collects metrics at
configurable intervals, detects bottlenecks, and compares results.
"""
import asyncio
import json
import logging
import os
import time
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DB_PATH = Path("/var/lib/lxc-siem-platform/platform.db")

# ── DB helpers (lightweight, avoids circular import with db.py) ──────────

@contextmanager
def _conn():
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    try:
        yield c
    finally:
        c.close()

def _now():
    return datetime.now(timezone.utc).isoformat()

def _save_benchmark(bm: dict):
    with _conn() as c:
        c.execute(
            """INSERT INTO benchmarks (benchmark_id,scenario_id,name,siem_type,status,config,phases,
               current_phase,results,started_at,completed_at,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(benchmark_id) DO UPDATE SET
               status=excluded.status,current_phase=excluded.current_phase,
               results=excluded.results,completed_at=excluded.completed_at""",
            (bm["benchmark_id"], bm["scenario_id"], bm.get("name"),
             bm.get("siem_type", "none"),
             bm["status"], json.dumps(bm.get("config", {})),
             json.dumps(bm.get("phases", [])), bm.get("current_phase", 0),
             json.dumps(bm.get("results", {})), bm.get("started_at"),
             bm.get("completed_at"), bm.get("created_at", _now())))
        c.commit()

def _record_bm_metric(benchmark_id: str, phase: int, category: str,
                      name: str, value: float, tags: str = None):
    with _conn() as c:
        c.execute(
            "INSERT INTO benchmark_metrics (benchmark_id,phase,category,metric_name,value,tags,recorded_at) VALUES (?,?,?,?,?,?,?)",
            (benchmark_id, phase, category, name, value, tags, _now()))
        c.commit()

def _record_bm_metrics_batch(benchmark_id: str, phase: int, rows: list):
    """rows: list of (category, name, value, tags)"""
    with _conn() as c:
        now = _now()
        c.executemany(
            "INSERT INTO benchmark_metrics (benchmark_id,phase,category,metric_name,value,tags,recorded_at) VALUES (?,?,?,?,?,?,?)",
            [(benchmark_id, phase, cat, n, v, t, now) for cat, n, v, t in rows])
        c.commit()

def _record_bottleneck(benchmark_id: str, phase: int, severity: str,
                       component: str, title: str, desc: str,
                       threshold: float, actual: float, recommendation: str):
    with _conn() as c:
        existing = c.execute(
            "SELECT id, occurrences FROM benchmark_bottlenecks WHERE benchmark_id=? AND component=? AND title=?",
            (benchmark_id, component, title)).fetchone()
        if existing:
            c.execute("UPDATE benchmark_bottlenecks SET occurrences=occurrences+1, actual_value=? WHERE id=?",
                      (actual, existing["id"]))
        else:
            c.execute(
                """INSERT INTO benchmark_bottlenecks (benchmark_id,phase,severity,component,title,
                   description,threshold,actual_value,recommendation,first_seen,occurrences)
                   VALUES (?,?,?,?,?,?,?,?,?,?,1)""",
                (benchmark_id, phase, severity, component, title, desc,
                 threshold, actual, recommendation, _now()))
        c.commit()


# ── Predefined Scenarios ─────────────────────────────────────────────────

SCENARIOS = {
    "linear_scale": {
        "id": "linear_scale",
        "name": "Linear Scale Test",
        "description": "Deploy agents in increasing increments to find maximum stable capacity",
        "phases": [
            {"agents": 5, "eps": 10, "duration": 120, "label": "Warmup (5 agents)"},
            {"agents": 10, "eps": 50, "duration": 300, "label": "Light (10 agents)"},
            {"agents": 25, "eps": 100, "duration": 300, "label": "Medium (25 agents)"},
            {"agents": 50, "eps": 200, "duration": 300, "label": "Heavy (50 agents)"},
            {"agents": 100, "eps": 500, "duration": 300, "label": "Max (100 agents)"},
        ],
        "failure_threshold": 0.20,
        "metric_interval": 15,
    },
    "burst_load": {
        "id": "burst_load",
        "name": "Burst Load Test",
        "description": "Sudden spike of agents and events to test resilience",
        "phases": [
            {"agents": 5, "eps": 10, "duration": 60, "label": "Baseline"},
            {"agents": 50, "eps": 1000, "duration": 120, "label": "Burst"},
            {"agents": 5, "eps": 10, "duration": 120, "label": "Recovery"},
        ],
        "failure_threshold": 0.30,
        "metric_interval": 10,
    },
    "sustained_load": {
        "id": "sustained_load",
        "name": "Sustained Load Test",
        "description": "Run at target capacity for extended duration to detect stability issues",
        "phases": [
            {"agents": 20, "eps": 200, "duration": 600, "label": "Sustained (20 agents, 10 min)"},
        ],
        "failure_threshold": 0.10,
        "metric_interval": 15,
    },
    "mixed_workload": {
        "id": "mixed_workload",
        "name": "Mixed Workload Test",
        "description": "Mix of SIEM types and simulation profiles",
        "phases": [
            {"agents": 10, "eps": 50, "duration": 180, "label": "Mixed deploy", "siem_types": ["wazuh", "ossec", "utmstack"]},
            {"agents": 10, "eps": 200, "duration": 180, "label": "Mixed sims", "profiles": ["auth_bruteforce", "web_attacks", "malware_beacon"]},
        ],
        "failure_threshold": 0.15,
        "metric_interval": 15,
    },
    "stress_test": {
        "id": "stress_test",
        "name": "Stress Test",
        "description": "Push the platform to breaking point to find absolute limits",
        "phases": [
            {"agents": 10, "eps": 100, "duration": 60, "label": "Ramp 1"},
            {"agents": 25, "eps": 500, "duration": 60, "label": "Ramp 2"},
            {"agents": 50, "eps": 1000, "duration": 60, "label": "Ramp 3"},
            {"agents": 100, "eps": 2000, "duration": 120, "label": "Ramp 4"},
            {"agents": 200, "eps": 5000, "duration": 120, "label": "Breaking Point"},
        ],
        "failure_threshold": 0.50,
        "metric_interval": 10,
    },
}


# ── Bottleneck Thresholds ────────────────────────────────────────────────

BOTTLENECK_RULES = [
    {"component": "siem_cpu", "metric": "system_cpu_percent", "threshold": 85,
     "severity": "critical", "title": "SIEM host CPU overloaded",
     "recommendation": "Consider vertical scaling or distributing agents across multiple managers"},
    {"component": "system_memory", "metric": "system_memory_percent", "threshold": 90,
     "severity": "critical", "title": "System memory critically high",
     "recommendation": "Reduce container count or increase host RAM"},
    {"component": "system_memory", "metric": "system_memory_percent", "threshold": 75,
     "severity": "warning", "title": "System memory usage elevated",
     "recommendation": "Monitor memory trend; consider reducing memory_limit per container"},
    {"component": "system_disk", "metric": "system_disk_percent", "threshold": 90,
     "severity": "critical", "title": "Disk space critically low",
     "recommendation": "Clean up logs and old containers; expand storage"},
    {"component": "deployment", "metric": "deploy_failure_rate", "threshold": 20,
     "severity": "critical", "title": "High deployment failure rate",
     "recommendation": "Check network connectivity and SIEM manager availability"},
    {"component": "deployment", "metric": "deploy_time_p90", "threshold": 300,
     "severity": "warning", "title": "Slow deployment times (P90 > 5 min)",
     "recommendation": "Enable agent package caching; check host I/O performance"},
    {"component": "platform_api", "metric": "api_latency_p90", "threshold": 5000,
     "severity": "warning", "title": "API response times degraded",
     "recommendation": "Check database performance and host CPU load"},
    {"component": "agent_disconnect", "metric": "agent_disconnect_rate", "threshold": 5,
     "severity": "warning", "title": "Agent disconnect rate exceeds 5%",
     "recommendation": "Check network capacity and SIEM manager connection limits"},
    {"component": "system_load", "metric": "system_load_per_core", "threshold": 2.0,
     "severity": "warning", "title": "CPU load significantly exceeds core count",
     "recommendation": "Reduce concurrent deployments or container count"},
]


# ── Metrics Collector ────────────────────────────────────────────────────

def collect_system_metrics() -> dict:
    """Collect current system resource metrics."""
    metrics = {}
    try:
        cpu_count = os.cpu_count() or 1
        with open("/proc/meminfo") as f:
            mi = f.read()
        import re
        mem_total = int(re.search(r"MemTotal:\s+(\d+)", mi).group(1)) // 1024
        mem_avail = int(re.search(r"MemAvailable:\s+(\d+)", mi).group(1)) // 1024
        mem_pct = ((mem_total - mem_avail) / mem_total * 100) if mem_total else 0

        with open("/proc/loadavg") as f:
            load = [float(x) for x in f.read().split()[:3]]

        st = os.statvfs("/")
        disk_total = (st.f_blocks * st.f_frsize) / (1024**3)
        disk_free = (st.f_bavail * st.f_frsize) / (1024**3)
        disk_pct = ((disk_total - disk_free) / disk_total * 100) if disk_total else 0

        metrics = {
            "system_cpu_count": cpu_count,
            "system_cpu_percent": min(load[0] / cpu_count * 100, 100),
            "system_load_1m": load[0],
            "system_load_per_core": load[0] / cpu_count,
            "system_memory_percent": mem_pct,
            "system_memory_available_mb": mem_avail,
            "system_disk_percent": disk_pct,
        }
    except Exception as e:
        logger.debug(f"System metric collection error: {e}")
    return metrics


def collect_container_metrics() -> dict:
    """Collect container-level aggregate metrics."""
    try:
        import lxc
        containers = lxc.list_containers()
        running = sum(1 for n in containers if lxc.Container(n).running)
        return {
            "containers_total": len(containers),
            "containers_running": running,
            "containers_stopped": len(containers) - running,
        }
    except Exception:
        return {"containers_total": 0, "containers_running": 0, "containers_stopped": 0}


def collect_all_metrics(benchmark_id: str, phase: int):
    """Collect and store all metric categories for one interval."""
    sys_m = collect_system_metrics()
    cnt_m = collect_container_metrics()

    rows = []
    for k, v in sys_m.items():
        rows.append(("system", k, v, None))
    for k, v in cnt_m.items():
        rows.append(("container", k, v, None))

    if rows:
        _record_bm_metrics_batch(benchmark_id, phase, rows)

    return {**sys_m, **cnt_m}


# ── Bottleneck Detector ──────────────────────────────────────────────────

def detect_bottlenecks(benchmark_id: str, phase: int, metrics: dict):
    """Check metrics against thresholds and record any bottlenecks."""
    metric_map = {
        "system_cpu_percent": metrics.get("system_cpu_percent", 0),
        "system_memory_percent": metrics.get("system_memory_percent", 0),
        "system_disk_percent": metrics.get("system_disk_percent", 0),
        "system_load_per_core": metrics.get("system_load_per_core", 0),
    }

    for rule in BOTTLENECK_RULES:
        val = metric_map.get(rule["metric"])
        if val is not None and val > rule["threshold"]:
            _record_bottleneck(
                benchmark_id, phase, rule["severity"], rule["component"],
                rule["title"], f'{rule["metric"]} = {val:.1f} (threshold: {rule["threshold"]})',
                rule["threshold"], val, rule["recommendation"],
            )


# ── Benchmark Engine ─────────────────────────────────────────────────────

# Active benchmarks tracked in-memory for WebSocket streaming
active_benchmarks: Dict[str, dict] = {}


async def run_benchmark(benchmark_id: str, scenario_id: str, config: dict):
    """Execute a full multi-phase benchmark."""
    scenario = SCENARIOS.get(scenario_id)
    if not scenario:
        raise ValueError(f"Unknown scenario: {scenario_id}")

    phases = config.get("phases") or scenario["phases"]
    metric_interval = config.get("metric_interval", scenario.get("metric_interval", 15))
    failure_threshold = config.get("failure_threshold", scenario.get("failure_threshold", 0.20))
    siem_type = config.get("siem_type", "none")
    siem_ip = config.get("siem_ip", "")
    base_name = config.get("base_name", f"bm-{benchmark_id[:8]}")

    bm = {
        "benchmark_id": benchmark_id,
        "scenario_id": scenario_id,
        "name": config.get("name") or scenario["name"],
        "siem_type": siem_type,
        "status": "running",
        "config": config,
        "phases": phases,
        "current_phase": 0,
        "results": {},
        "started_at": _now(),
        "completed_at": None,
        "created_at": _now(),
    }
    _save_benchmark(bm)
    active_benchmarks[benchmark_id] = bm

    phase_results = []
    aborted = False
    max_stable_agents = 0
    peak_eps = 0

    try:
        for i, phase in enumerate(phases):
            bm["current_phase"] = i
            bm["status"] = "running"
            _save_benchmark(bm)

            agents_count = phase.get("agents", 5)
            target_eps = phase.get("eps", 100)
            duration = phase.get("duration", 300)
            label = phase.get("label", f"Phase {i}")

            logger.info(f"[Benchmark {benchmark_id[:8]}] Phase {i}: {label} — {agents_count} agents, {target_eps} EPS, {duration}s")

            phase_start = time.time()
            phase_metrics = []
            deploy_times = []
            failures = 0

            # Deploy containers for this phase
            deploy_start = time.time()
            try:
                from main import deploy_single_siem_agent, get_or_create_agent_seq_id, write_agent_metadata, DB_PATH as MAIN_DB
                from concurrent.futures import ProcessPoolExecutor, as_completed
                from multiprocessing import cpu_count

                agent_names = [f"{base_name}-p{i}-{j:04d}" for j in range(1, agents_count + 1)]
                deployment_config = {
                    "siem_type": siem_type, "siem_ip": siem_ip,
                    "os_type": config.get("os_type", "ubuntu_22_04"),
                    "agent_group": config.get("agent_group", "benchmark"),
                    "memory_limit": config.get("memory_limit", "256MB"),
                    "cpu_shares": config.get("cpu_shares", 512),
                    "agent_base_name": base_name,
                    "siem_version": config.get("siem_version", ""),
                    "siem_auth_key": config.get("siem_auth_key", ""),
                }

                with ProcessPoolExecutor(max_workers=min(cpu_count(), agents_count)) as executor:
                    futures = {
                        executor.submit(deploy_single_siem_agent, name, deployment_config): name
                        for name in agent_names
                    }
                    for future in as_completed(futures):
                        try:
                            result = future.result(timeout=600)
                            dt = result.get("deploy_time_seconds", 0)
                            deploy_times.append(dt)
                            if not result.get("success"):
                                failures += 1
                        except Exception:
                            failures += 1

            except Exception as e:
                logger.error(f"[Benchmark {benchmark_id[:8]}] Deploy error in phase {i}: {e}")
                failures = agents_count

            deploy_elapsed = time.time() - deploy_start
            deploy_rate = (agents_count - failures) / (deploy_elapsed / 60) if deploy_elapsed > 0 else 0

            # Record deployment metrics
            deploy_times_sorted = sorted(deploy_times) if deploy_times else [0]
            n = len(deploy_times_sorted)
            dep_metrics = {
                "deploy_total": agents_count,
                "deploy_success": agents_count - failures,
                "deploy_failures": failures,
                "deploy_failure_rate": (failures / agents_count * 100) if agents_count else 0,
                "deploy_elapsed_seconds": deploy_elapsed,
                "deploy_rate_per_min": deploy_rate,
                "deploy_time_avg": sum(deploy_times) / n if n else 0,
                "deploy_time_p50": deploy_times_sorted[int(n * 0.5)] if n else 0,
                "deploy_time_p90": deploy_times_sorted[int(n * 0.9)] if n else 0,
                "deploy_time_p99": deploy_times_sorted[min(int(n * 0.99), n - 1)] if n else 0,
                "deploy_time_min": deploy_times_sorted[0] if n else 0,
                "deploy_time_max": deploy_times_sorted[-1] if n else 0,
            }

            _record_bm_metrics_batch(benchmark_id, i,
                [("deployment", k, v, None) for k, v in dep_metrics.items()])

            # Check early termination
            if agents_count > 0 and failures / agents_count > failure_threshold:
                logger.warning(f"[Benchmark {benchmark_id[:8]}] Failure threshold exceeded in phase {i}")
                phase_result = {
                    "phase": i, "label": label, "status": "aborted",
                    "reason": f"Failure rate {failures/agents_count*100:.0f}% exceeded threshold {failure_threshold*100:.0f}%",
                    **dep_metrics,
                }
                phase_results.append(phase_result)
                aborted = True
                break

            # Monitoring loop: collect metrics at intervals during the duration
            monitoring_start = time.time()
            while time.time() - monitoring_start < duration:
                m = collect_all_metrics(benchmark_id, i)
                detect_bottlenecks(benchmark_id, i, m)
                phase_metrics.append(m)

                # Update active benchmark for WebSocket
                bm["results"]["live"] = {
                    "phase": i, "label": label, "elapsed": time.time() - phase_start,
                    "metrics": m, "deploy": dep_metrics,
                }
                await asyncio.sleep(metric_interval)

            # Check if benchmark was stopped externally
            if bm.get("status") == "stopped":
                aborted = True
                break

            successful_agents = agents_count - failures
            if successful_agents > max_stable_agents:
                max_stable_agents = successful_agents
            if target_eps > peak_eps:
                peak_eps = target_eps

            phase_result = {
                "phase": i, "label": label, "status": "completed",
                "agents": agents_count, "target_eps": target_eps,
                "duration": duration,
                **dep_metrics,
                "system_metrics_samples": len(phase_metrics),
            }
            phase_results.append(phase_result)

    except Exception as e:
        logger.error(f"[Benchmark {benchmark_id[:8]}] Fatal error: {e}")
        bm["status"] = "failed"
        bm["results"]["error"] = str(e)

    # Finalize
    bm["status"] = "aborted" if aborted else "completed"
    bm["completed_at"] = _now()
    bm["results"]["phases"] = phase_results
    bm["results"]["summary"] = _build_summary(benchmark_id, phase_results, max_stable_agents, peak_eps)
    _save_benchmark(bm)

    active_benchmarks.pop(benchmark_id, None)
    logger.info(f"[Benchmark {benchmark_id[:8]}] {bm['status'].upper()} — max agents: {max_stable_agents}, peak EPS: {peak_eps}")

    return bm


def _build_summary(benchmark_id: str, phase_results: list,
                   max_agents: int, peak_eps: int) -> dict:
    """Build executive summary from phase results."""
    total_deploys = sum(p.get("deploy_total", 0) for p in phase_results)
    total_success = sum(p.get("deploy_success", 0) for p in phase_results)
    total_failures = sum(p.get("deploy_failures", 0) for p in phase_results)
    all_deploy_times = []
    for p in phase_results:
        avg = p.get("deploy_time_avg", 0)
        if avg > 0:
            all_deploy_times.append(avg)

    # Get bottlenecks
    with _conn() as c:
        bottlenecks = [dict(r) for r in c.execute(
            "SELECT * FROM benchmark_bottlenecks WHERE benchmark_id=? ORDER BY severity, occurrences DESC",
            (benchmark_id,)).fetchall()]

    critical_bottlenecks = [b for b in bottlenecks if b["severity"] == "critical"]
    verdict = "PASS"
    if critical_bottlenecks:
        verdict = "FAIL"
    elif total_failures > 0 and total_deploys > 0 and total_failures / total_deploys > 0.05:
        verdict = "WARN"

    return {
        "verdict": verdict,
        "max_stable_agents": max_agents,
        "peak_eps_target": peak_eps,
        "total_deployments": total_deploys,
        "successful_deployments": total_success,
        "failed_deployments": total_failures,
        "success_rate_percent": round(total_success / total_deploys * 100, 1) if total_deploys else 0,
        "avg_deploy_time_seconds": round(sum(all_deploy_times) / len(all_deploy_times), 1) if all_deploy_times else 0,
        "phases_completed": len([p for p in phase_results if p.get("status") == "completed"]),
        "phases_total": len(phase_results),
        "bottlenecks_critical": len(critical_bottlenecks),
        "bottlenecks_total": len(bottlenecks),
        "bottleneck_details": bottlenecks[:10],
    }


# ── Comparison Engine ────────────────────────────────────────────────────

def compare_benchmarks(benchmark_ids: List[str]) -> dict:
    """Compare two or more benchmarks side-by-side."""
    benchmarks = []
    with _conn() as c:
        for bid in benchmark_ids:
            row = c.execute("SELECT * FROM benchmarks WHERE benchmark_id=?", (bid,)).fetchone()
            if row:
                bm = dict(row)
                bm["results"] = json.loads(bm.get("results") or "{}")
                bm["config"] = json.loads(bm.get("config") or "{}")
                benchmarks.append(bm)

    if len(benchmarks) < 2:
        return {"error": "Need at least 2 benchmarks to compare"}

    comparison = {"benchmarks": [], "winner": None, "improvements": [], "regressions": []}
    best_score = -1
    best_id = None

    for bm in benchmarks:
        summary = bm.get("results", {}).get("summary", {})
        entry = {
            "benchmark_id": bm["benchmark_id"],
            "name": bm.get("name"),
            "scenario_id": bm["scenario_id"],
            "siem_type": bm.get("config", {}).get("siem_type") or bm.get("siem_type", "none"),
            "status": bm["status"],
            "started_at": bm.get("started_at"),
            "max_agents": summary.get("max_stable_agents", 0),
            "success_rate": summary.get("success_rate_percent", 0),
            "avg_deploy_time": summary.get("avg_deploy_time_seconds", 0),
            "verdict": summary.get("verdict", "N/A"),
            "bottlenecks": summary.get("bottlenecks_total", 0),
        }
        comparison["benchmarks"].append(entry)

        # Score: higher agents + higher success rate + lower deploy time = better
        score = (entry["max_agents"] * 10
                 + entry["success_rate"]
                 - entry["avg_deploy_time"]
                 - entry["bottlenecks"] * 5)
        if score > best_score:
            best_score = score
            best_id = bm["benchmark_id"]

    comparison["winner"] = best_id

    # Compare first vs last (baseline vs current)
    if len(comparison["benchmarks"]) >= 2:
        base = comparison["benchmarks"][0]
        curr = comparison["benchmarks"][-1]
        for key in ["max_agents", "success_rate", "avg_deploy_time"]:
            bv, cv = base[key], curr[key]
            if bv == 0 and cv == 0:
                continue
            lower_better = key == "avg_deploy_time"
            improved = (cv < bv) if lower_better else (cv > bv)
            delta = cv - bv
            pct = round(abs(delta) / bv * 100, 1) if bv else 0
            entry = {"metric": key, "baseline": bv, "current": cv, "delta": round(delta, 2), "percent_change": pct}
            if improved:
                comparison["improvements"].append(entry)
            elif delta != 0:
                comparison["regressions"].append(entry)

    # Natural language summary
    if comparison["winner"]:
        w = next(b for b in comparison["benchmarks"] if b["benchmark_id"] == comparison["winner"])
        comparison["summary"] = (
            f'Best performing: "{w["name"]}" with {w["max_agents"]} max agents, '
            f'{w["success_rate"]}% success rate, {w["avg_deploy_time"]}s avg deploy. '
            f'Verdict: {w["verdict"]}.'
        )

    return comparison


# ── Query Helpers ────────────────────────────────────────────────────────

def get_benchmark(benchmark_id: str) -> Optional[dict]:
    with _conn() as c:
        row = c.execute("SELECT * FROM benchmarks WHERE benchmark_id=?", (benchmark_id,)).fetchone()
        if not row:
            return None
        bm = dict(row)
        bm["results"] = json.loads(bm.get("results") or "{}")
        bm["config"] = json.loads(bm.get("config") or "{}")
        bm["phases"] = json.loads(bm.get("phases") or "[]")
        return bm

def list_benchmarks() -> list:
    with _conn() as c:
        rows = c.execute("SELECT benchmark_id, scenario_id, name, siem_type, status, current_phase, started_at, completed_at, created_at FROM benchmarks ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]

def get_benchmark_metrics(benchmark_id: str, category: str = None, limit: int = 1000) -> list:
    with _conn() as c:
        sql = "SELECT * FROM benchmark_metrics WHERE benchmark_id=?"
        params: list = [benchmark_id]
        if category:
            sql += " AND category=?"
            params.append(category)
        sql += " ORDER BY recorded_at DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in c.execute(sql, params).fetchall()]

def cleanup_stale_benchmarks() -> int:
    """Mark any 'running' benchmarks as 'aborted' if they have no active in-memory task.

    Called at startup and can be triggered manually. Handles cases where
    the server crashed or the host went to sleep mid-benchmark.
    """
    with _conn() as c:
        rows = c.execute("SELECT benchmark_id FROM benchmarks WHERE status = 'running'").fetchall()
        cleaned = 0
        now = _now()
        for row in rows:
            bid = row["benchmark_id"]
            if bid not in active_benchmarks:
                c.execute(
                    "UPDATE benchmarks SET status = 'aborted', completed_at = ?, results = json_set(COALESCE(results, '{}'), '$.abort_reason', 'Server restart or crash recovery') WHERE benchmark_id = ?",
                    (now, bid)
                )
                cleaned += 1
                logger.info(f"Cleaned up stale benchmark {bid[:8]} → aborted")
        if cleaned:
            c.commit()
    return cleaned


def get_benchmark_bottlenecks(benchmark_id: str) -> list:
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM benchmark_bottlenecks WHERE benchmark_id=? ORDER BY severity, occurrences DESC",
            (benchmark_id,)).fetchall()]
