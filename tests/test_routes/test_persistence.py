"""
Jobs and schedules survive a restart: records are persisted, in-place changes are
flushed, running ones come back as "interrupted", and log schedules resume.
"""
import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app import migrations
from app.services import logs as log_service
from app.services.records import INTERRUPTED, PersistentStore


@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "platform.db"
    migrations.migrate(path)
    return path


def _restart(db, kind, **kwargs):
    """A fresh store loaded from the database, as after a restart."""
    store = PersistentStore(kind, **kwargs)
    interrupted = store.load(db)
    return store, interrupted


def test_records_survive_a_restart(db):
    store, _ = _restart(db, "simulation")
    store["s1"] = {"simulation_id": "s1", "status": "running", "events_generated": 0, "task": object()}
    store["s2"] = {"simulation_id": "s2", "status": "completed", "events_generated": 50}
    store["s1"]["events_generated"] = 1234  # changed in place by a background task...
    assert store.flush() == 1  # ...and saved by the periodic flush

    after, interrupted = _restart(db, "simulation")
    assert interrupted == ["s1"]
    assert after["s1"]["status"] == INTERRUPTED and after["s1"]["status_before_restart"] == "running"
    assert after["s1"]["events_generated"] == 1234 and "task" not in after["s1"]  # transient not saved
    assert after["s2"]["status"] == "completed"  # finished ones unchanged


def test_delete_and_pop_remove_from_the_database(db):
    store, _ = _restart(db, "report")
    store["a"] = {"x": 1}
    store["b"] = {"x": 2}
    del store["a"]
    assert store.pop("b")["x"] == 2 and store.pop("missing", None) is None
    after, _ = _restart(db, "report")
    assert dict(after) == {}


def test_prune_forgets_old_finished_records_only(db):
    store, _ = _restart(db, "deployment")
    store["old-done"] = {"status": "completed"}
    store["old-running"] = {"status": "running"}
    store["new-done"] = {"status": "failed"}
    old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
    conn = sqlite3.connect(db)
    conn.execute("UPDATE records SET updated_at = ? WHERE id IN ('old-done', 'old-running')", (old,))
    conn.commit()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
    assert store.prune(cutoff) == 1
    assert set(store) == {"old-running", "new-done"}

    templates, _ = _restart(db, "config_template", prunable=False)
    templates["t"] = {"name": "kept"}
    conn.execute("UPDATE records SET updated_at = ? WHERE kind = 'config_template'", (old,))
    conn.commit()
    assert templates.prune(cutoff) == 0


def test_config_templates_survive_a_restart(client):
    from app.config import DB_PATH
    resp = client.post("/configs/import", json={"name": "persisted-template", "siem_type": "wazuh",
                                                "content": "<ossec_config/>"})
    assert resp.status_code == 200, resp.text
    template_id = resp.json()["data"]["template_id"]
    after, _ = _restart(DB_PATH, "config_template", prunable=False)
    assert after[template_id]["name"] == "persisted-template"


def test_template_files_from_before_are_imported(app, tmp_path, monkeypatch, db):
    import json

    from app import state
    configs = tmp_path / "configs"
    configs.mkdir()
    (configs / "t-old.json").write_text(json.dumps({"template_id": "t-old", "name": "from a file"}))
    (configs / "junk.json").write_text("not json")
    store, _ = _restart(db, "config_template", prunable=False)
    monkeypatch.setattr(state, "config_templates", store)
    assert state.import_legacy_config_templates(configs) == 1
    assert store["t-old"]["name"] == "from a file"
    assert state.import_legacy_config_templates(configs) == 0  # only once


def _schedule(created_minutes_ago, duration, indefinite=False, status_before="running"):
    return {
        "schedule_id": "x", "agent_id": "c1", "interval_seconds": 60, "duration_seconds": duration,
        "indefinite": indefinite, "status": INTERRUPTED, "status_before_restart": status_before, "runs": 7,
        "created_at": (datetime.now(timezone.utc) - timedelta(minutes=created_minutes_ago)).isoformat(),
        "request": {"content": "hello", "destination_path": "/var/log/test.log", "log_type": "custom",
                    "append": True},
    }


def test_log_schedules_resume_for_their_remaining_time(db, monkeypatch):
    store, _ = _restart(db, "log_schedule")
    monkeypatch.setattr(log_service, "scheduled_log_tasks", store)
    started = []

    async def fake_run(schedule_id, agent_id, log_upload, interval, duration, indefinite):
        started.append((schedule_id, agent_id, log_upload.content, interval, duration, indefinite))

    monkeypatch.setattr(log_service, "run_log_schedule", fake_run)
    store["timed"] = _schedule(created_minutes_ago=10, duration=3600)
    store["forever"] = _schedule(created_minutes_ago=600, duration=None, indefinite=True)
    store["expired"] = _schedule(created_minutes_ago=120, duration=3600)
    store["was-stopped"] = _schedule(created_minutes_ago=1, duration=3600, status_before="stopped")

    async def run():
        count = log_service.resume_log_schedules()
        await asyncio.sleep(0)  # let the tasks start
        return count

    assert asyncio.run(run()) == 2
    by_id = {s[0]: s for s in started}
    assert set(by_id) == {"timed", "forever"}
    assert 2900 < by_id["timed"][4] <= 3000  # about 50 of its 60 minutes left
    assert by_id["forever"][4] is None and by_id["forever"][5] is True
    assert by_id["timed"][2] == "hello"  # the upload itself was kept
    assert store["timed"]["resumes"] == 1 and store["timed"]["runs"] == 7
    assert store["expired"]["status"] == "completed"
    assert store["was-stopped"]["status"] == INTERRUPTED  # left alone


def test_schedule_api_hides_the_stored_request(client, monkeypatch):
    from app.services.logs import schedule_public
    public = schedule_public({"schedule_id": "s", "task": object(), "request": {"content": "secret-ish"}})
    assert public == {"schedule_id": "s"}
