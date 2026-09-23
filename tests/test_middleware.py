"""
Which requests reach the API and which get the UI (StripApiPrefixMiddleware).
"""
import asyncio

import pytest

from app import middleware

HTML = [(b"accept", b"text/html,application/xhtml+xml,*/*;q=0.8")]
JSON = [(b"accept", b"application/json")]


@pytest.fixture()
def static(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<!DOCTYPE html>")
    (tmp_path / "favicon.svg").write_text("<svg/>")
    monkeypatch.setattr(middleware, "STATIC_DIR", tmp_path)
    return tmp_path


def _routed_path(path, headers, method="GET", kind="http"):
    seen = {}

    async def inner(scope, receive, send):
        seen["path"] = scope["path"]

    scope = {"type": kind, "method": method, "path": path, "headers": headers}
    asyncio.run(middleware.StripApiPrefixMiddleware(inner)(scope, None, None))
    return seen["path"]


@pytest.mark.parametrize("path", ["/", "/agents", "/groups", "/account", "/reports"])
def test_browser_page_loads_get_the_ui(static, path):
    # e.g. reloading the Containers page (/agents), which is also an API path
    assert _routed_path(path, HTML) == "/index.html"


@pytest.mark.parametrize("path,headers,method,kind,expected", [
    ("/api/agents", HTML, "GET", "http", "/agents"),   # the UI's own API calls
    ("/agents", JSON, "GET", "http", "/agents"),       # API clients without the prefix
    ("/agents", HTML, "POST", "http", "/agents"),
    ("/ws/metrics", HTML, "GET", "websocket", "/ws/metrics"),
    ("/favicon.svg", HTML, "GET", "http", "/favicon.svg"),
    ("/assets/index.js", HTML, "GET", "http", "/assets/index.js"),
])
def test_everything_else_is_left_alone(static, path, headers, method, kind, expected):
    assert _routed_path(path, headers, method, kind) == expected


def test_no_ui_rewrite_without_a_build(tmp_path, monkeypatch):
    monkeypatch.setattr(middleware, "STATIC_DIR", tmp_path)
    assert _routed_path("/agents", HTML) == "/agents"
