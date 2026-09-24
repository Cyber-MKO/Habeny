"""
Graceful shutdown: a stop lets running deployments finish, cancels queued ones, gives up
at the deadline, and refuses new changes meanwhile.
"""
import threading
import time

import pytest

import app.services.deployment as dep
from app.services import lifecycle


def _slow_deploy(agent_name, deployment_config, agent_seq_id=None, progress_queue=None):
    time.sleep(1.5)
    return {"agent_name": agent_name, "agent_seq_id": agent_seq_id, "success": True,
            "deploy_time_seconds": 1.5, "metadata": {"agent_seq_id": agent_seq_id, "lifecycle_status": "running"}}


@pytest.fixture()
def one_worker(app, monkeypatch):
    monkeypatch.setattr(dep, "DEPLOY_WORKERS", 1)
    monkeypatch.setattr(dep, "deploy_single_siem_agent", _slow_deploy)
    lifecycle._reset_for_tests()
    yield
    lifecycle._reset_for_tests()


def _deploy_in_background(names):
    out = {}

    from app.config import DB_PATH
    from app.db import get_or_create_agent_seq_id
    seq_ids = {n: get_or_create_agent_seq_id(DB_PATH, n) for n in names}

    def run():
        out["results"], out["warnings"] = dep.run_deployment_workers(
            "shutdown-test", names, {"siem_type": "none"}, seq_ids)
    thread = threading.Thread(target=run)
    thread.start()
    return thread, out


def test_stop_finishes_running_and_cancels_queued(one_worker):
    names = ["gs-0001", "gs-0002", "gs-0003", "gs-0004"]
    thread, out = _deploy_in_background(names)
    time.sleep(0.5)  # first container is being deployed
    lifecycle.begin_shutdown()
    thread.join(timeout=20)
    by_name = {r["agent_name"]: r for r in out["results"]}
    assert set(by_name) == set(names)  # every container is accounted for
    assert by_name["gs-0001"]["success"] is True  # running one finished
    assert by_name["gs-0004"]["success"] is False and by_name["gs-0004"]["error"].startswith("Cancelled")
    # nothing started after the stop: only the container already running finished
    assert [r["agent_name"] for r in out["results"] if r["success"]] == ["gs-0001"]
    assert all(by_name[n]["error"].startswith("Cancelled") for n in names[1:])


def test_deadline_abandons_running_containers(one_worker, monkeypatch):
    thread, out = _deploy_in_background(["gd-0001", "gd-0002"])
    time.sleep(0.5)
    lifecycle.begin_shutdown()
    monkeypatch.setattr(lifecycle, "_deadline", time.monotonic())  # no time left
    started = time.monotonic()
    thread.join(timeout=20)
    assert time.monotonic() - started < 1.2  # didn't wait for the 1.5s deploy
    first = next(r for r in out["results"] if r["agent_name"] == "gd-0001")
    assert first["success"] is False and first["error"].startswith("Interrupted")

    from app.services.agent_info import read_agent_metadata
    assert read_agent_metadata("gd-0001")["lifecycle_status"] == lifecycle.INTERRUPTED


def test_changes_are_refused_while_stopping(client):
    lifecycle._reset_for_tests()
    try:
        lifecycle.begin_shutdown()
        resp = client.post("/groups", json={"name": "late-group"})
        assert resp.status_code == 503 and resp.headers["retry-after"] == "60"
        assert client.get("/groups").status_code == 200  # reads still work
    finally:
        lifecycle._reset_for_tests()


def test_startup_marks_leftover_deployments_interrupted(app):
    from app.services.agent_info import read_agent_metadata, write_agent_metadata

    write_agent_metadata("gr-0001", {"lifecycle_status": "starting"})
    assert lifecycle.recover_interrupted_deployments() >= 1
    assert read_agent_metadata("gr-0001")["lifecycle_status"] == lifecycle.INTERRUPTED


def test_stop_interrupts_simulations_instead_of_waiting(app):
    from app.state import simulations_db
    simulations_db["sim-stop-test"] = {"simulation_id": "sim-stop-test", "status": "running"}
    lifecycle._reset_for_tests()
    try:
        lifecycle.begin_shutdown()
        assert simulations_db["sim-stop-test"]["status"] == "interrupted"
        assert simulations_db["sim-stop-test"]["status_before_restart"] == "running"
    finally:
        lifecycle._reset_for_tests()
        simulations_db.pop("sim-stop-test", None)


def test_attack_simulation_honours_stop(app, monkeypatch):
    """The loop used to ignore Stop and run for its whole duration, then report "completed"."""
    import asyncio

    from app.services import simulation
    from app.state import simulations_db

    monkeypatch.setattr(simulation, "generate_simulation_events", lambda *a: {"events": 1})
    simulations_db["sim-attack"] = {"simulation_id": "sim-attack", "status": "running"}

    async def scenario():
        task = asyncio.create_task(simulation.run_simulation("sim-attack", "p", ["c1"], 60, 1))
        await asyncio.sleep(1.2)
        simulations_db["sim-attack"]["status"] = "stopped"  # what the Stop button does
        await asyncio.wait_for(task, timeout=5)

    started = time.monotonic()
    asyncio.run(scenario())
    assert time.monotonic() - started < 5
    assert simulations_db["sim-attack"]["status"] == "stopped"
    simulations_db.pop("sim-attack")


def test_stop_interrupts_log_schedules_so_they_resume(app, monkeypatch):
    import asyncio

    from app.models import LogUploadRequest
    from app.services import logs as log_service
    from app.state import scheduled_log_tasks

    async def fake_upload(agent_id, log_upload):
        return {"success": True}

    monkeypatch.setattr(log_service, "perform_log_upload", fake_upload)
    monkeypatch.setattr(log_service.lxc, "list_containers", lambda *a, **k: ["c1"])
    scheduled_log_tasks["sched-stop"] = {"schedule_id": "sched-stop", "agent_id": "c1", "status": "starting"}

    async def scenario():
        task = asyncio.create_task(log_service.run_log_schedule(
            "sched-stop", "c1", LogUploadRequest(content="x", destination_path="/var/log/x.log"), 5, None, True))
        scheduled_log_tasks["sched-stop"]["task"] = task
        await asyncio.sleep(0.2)
        log_service.interrupt_for_shutdown()
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=5)

    asyncio.run(scenario())
    record = scheduled_log_tasks.pop("sched-stop")
    assert record["status"] == "interrupted" and record["status_before_restart"] == "running"
