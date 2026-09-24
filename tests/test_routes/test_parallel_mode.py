"""
The deployment's parallel_mode is honoured: separate processes, one at a time, or threads.
"""
import os
import threading
import time

import pytest

import app.services.deployment as dep


def _timed_deploy(agent_name, deployment_config, agent_seq_id=None, progress_queue=None):
    started = time.time()
    time.sleep(0.4)
    return {"agent_name": agent_name, "success": True, "pid": os.getpid(), "thread": threading.get_ident(),
            "started": started, "ended": time.time(), "metadata": {}}


@pytest.fixture()
def fake_deploy(app, monkeypatch):
    monkeypatch.setattr(dep, "deploy_single_siem_agent", _timed_deploy)
    monkeypatch.setattr(dep, "DEPLOY_WORKERS", 3)
    monkeypatch.setattr(dep, "persist_deploy_result", lambda result, siem_type=None: None)


def _run(mode, n=3):
    names = [f"pm-{mode[:4]}-{i}" for i in range(n)]
    results, _ = dep.run_deployment_workers("pm-test", names, {"siem_type": "none"},
                                            {name: i for i, name in enumerate(names, 1)}, mode)
    return sorted(results, key=lambda r: r["started"])


def _overlap(results):
    return any(b["started"] < a["ended"] for a, b in zip(results, results[1:], strict=False))


def test_multiprocessing_runs_in_parallel_processes(fake_deploy):
    results = _run("multiprocessing")
    assert all(r["pid"] != os.getpid() for r in results)
    assert _overlap(results)


def test_sequential_deploys_one_at_a_time(fake_deploy):
    results = _run("sequential")
    assert all(r["pid"] != os.getpid() for r in results)  # still isolated in a worker process
    assert not _overlap(results)


def test_threading_runs_in_the_app_process(fake_deploy):
    results = _run("threading")
    assert all(r["pid"] == os.getpid() for r in results)
    assert len({r["thread"] for r in results}) > 1 and _overlap(results)


def test_worker_count():
    assert dep.worker_count("sequential", 50) == 1
    assert dep.worker_count("threading", 2) == 2
    assert dep.worker_count("multiprocessing", 10_000) == dep.DEPLOY_WORKERS


def test_route_passes_the_mode(client):
    resp = client.post("/agents/deploy", json={"count": 1, "siem_type": "none", "agent_base_name": "pmroute",
                                               "parallel_mode": "sequential", "deployment_id": "pm-route-1"})
    assert resp.status_code == 200, resp.text
    events = client.get("/agents/deploy/progress/pm-route-1").json()["data"]["events"]
    assert any("Launching 1 deployment worker (sequential)" in e["message"] for e in events)
