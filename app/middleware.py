"""
HTTP middleware: /api prefix stripping and API latency tracking.
"""
import time

from app.config import DB_PATH
from app.db import record_metric


class StripApiPrefixMiddleware:
    """The built frontend calls the API under /api (the Vite dev proxy strips it
    the same way), so accept /api/... when the UI is served from this server."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            path = scope.get("path", "")
            if path == "/api" or path.startswith("/api/"):
                scope = dict(scope, path=path[4:] or "/", raw_path=None)
        await self.app(scope, receive, send)


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
    return response
