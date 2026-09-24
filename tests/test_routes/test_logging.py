"""
Request IDs, access log, error responses, JSON logs, log rotation, latency sampling.
"""
import io
import json
import logging
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import logging_config, middleware
from app.logging_config import ContextFilter, JsonFormatter


@pytest.fixture()
def captured():
    """Log records as the real handlers see them (with the request context filter)."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(ContextFilter())
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.addHandler(handler)
    old_level = root.level
    root.setLevel(logging.INFO)
    yield lambda: [json.loads(line) for line in stream.getvalue().splitlines()]
    root.removeHandler(handler)
    root.setLevel(old_level)


def test_every_response_has_a_request_id(client):
    first = client.get("/system/health").headers["X-Request-ID"]
    second = client.get("/system/health").headers["X-Request-ID"]
    assert len(first) == 16 and first != second


def test_valid_incoming_request_id_is_kept(client):
    resp = client.get("/system/health", headers={"X-Request-ID": "proxy-abc-12345"})
    assert resp.headers["X-Request-ID"] == "proxy-abc-12345"
    bad = client.get("/system/health", headers={"X-Request-ID": "bad id\nwith newline"})
    assert bad.headers["X-Request-ID"] != "bad id\nwith newline"


def test_access_log_line_carries_id_and_user(client, captured):
    resp = client.get("/groups")
    rid = resp.headers["X-Request-ID"]
    access = [e for e in captured() if e["logger"] == "habeny.access" and e.get("request_id") == rid]
    assert len(access) == 1
    entry = access[0]
    assert entry["user"] == "admin" and entry["status"] == 200 and entry["path"] == "/groups"
    assert entry["method"] == "GET" and entry["duration_ms"] >= 0


def test_unhandled_error_returns_500_with_request_id(app, client, captured):
    def boom():
        logging.getLogger("app.test").info("about to fail")
        raise RuntimeError("kaboom")

    app.add_api_route("/test-boom", boom, methods=["POST"])
    resp = TestClient(app, raise_server_exceptions=False).post("/test-boom")
    assert resp.status_code == 500
    rid = resp.headers["X-Request-ID"]
    assert resp.json()["request_id"] == rid and "kaboom" not in resp.text  # no internals leaked
    mine = [e for e in captured() if e.get("request_id") == rid]
    assert any(e["message"] == "about to fail" for e in mine)  # app logs carry the ID too
    error = next(e for e in mine if e["level"] == "error")
    assert "RuntimeError: kaboom" in error["exception"]


def test_activity_entries_record_request_and_user(client):
    resp = client.post("/groups", json={"name": "logging-test-group"})
    rid = resp.headers["X-Request-ID"]
    entries = client.get("/activity/logs", params={"limit": 20}).json()["data"]["logs"]
    mine = [e for e in entries if e.get("request_id") == rid]
    assert mine and mine[0]["user"] == "admin"


def test_latency_samples_are_buffered_then_saved(client):
    from app.config import DB_PATH

    middleware.flush_latency_samples()
    client.get("/system/health", headers={"X-Request-ID": "latency-probe-1"})
    assert middleware.flush_latency_samples() >= 1
    row = sqlite3.connect(DB_PATH).execute(
        "SELECT metric_name, tags FROM metrics WHERE metric_type='api_latency' ORDER BY id DESC LIMIT 1").fetchone()
    assert row == ("/system/health", "GET")


def test_text_and_json_formats_and_rotation(tmp_path):
    root = logging.getLogger()
    saved = (list(root.handlers), root.level)
    log_file = tmp_path / "logs" / "habeny.log"
    try:
        logging_config.configure(level="info", fmt="json", log_file=str(log_file), max_mb=1, backups=2)
        token = logging_config.request_context.set({"id": "rid-rotation-01", "user": "alice"})
        log = logging.getLogger("app.test.rotation")
        log.info("structured", extra={"fields": {"containers": 3}})
        first = json.loads(log_file.read_text().splitlines()[0])
        assert first["message"] == "structured" and first["containers"] == 3
        assert first["request_id"] == "rid-rotation-01" and first["user"] == "alice"
        logging_config.request_context.reset(token)
        for _ in range(3000):  # ~1.2 MB: rotates once
            log.info("x" * 400)
        rotated = sorted(p.name for p in log_file.parent.iterdir())
        assert rotated == ["habeny.log", "habeny.log.1"]

        logging_config.configure(level="info", fmt="text")
        stream = io.StringIO()
        root.handlers[0].stream = stream
        log.info("plain")
        assert stream.getvalue().rstrip().endswith("INFO    app.test.rotation [-] plain")
    finally:
        for handler in list(root.handlers):
            root.removeHandler(handler)
            handler.close()
        for handler in saved[0]:
            root.addHandler(handler)
        root.setLevel(saved[1])
