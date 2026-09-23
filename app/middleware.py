"""
HTTP middleware: /api prefix stripping and API latency tracking.
"""
import time

from app.config import DB_PATH, STATIC_DIR
from app.db import record_metric
from app.tls import hsts_enabled

HSTS = hsts_enabled()


class StripApiPrefixMiddleware:
    """The built frontend calls the API under /api (the Vite dev proxy strips it
    the same way), so accept /api/... when the UI is served from this server.

    A browser page load (GET asking for HTML) outside /api always gets the UI, so
    reloading or bookmarking a page whose path is also an API path (/agents,
    /groups, ...) works. The UI itself only calls the API under /api, and non-HTML
    clients still reach the API without the prefix."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            path = scope.get("path", "")
            if path == "/api" or path.startswith("/api/"):
                scope = dict(scope, path=path[4:] or "/", raw_path=None)
            elif _is_page_load(scope, path):
                scope = dict(scope, path="/index.html", raw_path=None)
        await self.app(scope, receive, send)


def _is_page_load(scope, path: str) -> bool:
    if scope["type"] != "http" or scope.get("method") != "GET" or not _wants_html(scope):
        return False
    if path.startswith("/assets/") or not (STATIC_DIR / "index.html").is_file():
        return False
    static_file = (STATIC_DIR / path.lstrip("/")).resolve()
    return not (static_file.is_relative_to(STATIC_DIR.resolve()) and static_file.is_file())


def _wants_html(scope) -> bool:
    for name, value in scope.get("headers", []):
        if name == b"accept":
            return b"text/html" in value
    return False


async def track_request_latency(request, call_next):
    start = time.time()
    response = await call_next(request)
    latency_ms = (time.time() - start) * 1000
    path = request.url.path
    # Record latency for API endpoints (skip static files)
    if not path.startswith("/assets") and path != "/favicon.ico":
        try:
            record_metric(DB_PATH, "api_latency", path, latency_ms, request.method)
        except Exception:
            pass
    response.headers["X-Response-Time-Ms"] = f"{latency_ms:.1f}"
    if request.url.scheme == "https" and HSTS:
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    return response
