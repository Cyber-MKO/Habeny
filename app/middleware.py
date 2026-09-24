"""
HTTP middleware: request IDs and access logging, /api prefix stripping.
"""
import logging
import re
import time
import uuid
from collections import deque
from datetime import datetime, timezone

from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse

from app.config import DB_PATH, STATIC_DIR
from app.db import record_metrics_batch
from app.logging_config import request_context
from app.tls import hsts_enabled

logger = logging.getLogger(__name__)
access_logger = logging.getLogger("habeny.access")

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


class RequestContextMiddleware:
    """Outermost: gives every request (and WebSocket) an ID, logs it, times it.

    - The ID comes from a valid incoming X-Request-ID (e.g. set by a reverse proxy) or is
      generated; it's returned in X-Request-ID and attached to every log line.
    - One access-log line per request, with method, path, status, duration and user.
    - An unhandled error is logged with its traceback and answered with a 500 that
      carries the request ID, so a user can report it and it can be found in the logs.
    - API latency samples are buffered and saved in batches (see flush_latency_samples).
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        incoming = next((v for k, v in scope.get("headers", []) if k == b"x-request-id"), b"")
        request_id = incoming.decode() if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex[:16]
        ctx = {"id": request_id, "user": None, "ip": (scope.get("client") or (None,))[0]}
        token = request_context.set(ctx)
        started = time.perf_counter()
        state = {"status": None}

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                state["status"] = message["status"]
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
                headers["X-Response-Time-Ms"] = f"{(time.perf_counter() - started) * 1000:.1f}"
                if HSTS and scope.get("scheme") == "https":
                    headers["Strict-Transport-Security"] = "max-age=31536000"
            elif message["type"] == "websocket.accept":
                state["status"] = 101
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        except Exception:
            logger.exception("Unhandled error in %s %s", scope.get("method", "WS"), scope.get("path"))
            if scope["type"] == "http" and state["status"] is None:
                response = JSONResponse(
                    {"detail": "Internal server error. Quote this request ID when reporting it.",
                     "request_id": request_id},
                    status_code=500,
                )
                await response(scope, receive, send_with_headers)
            state["status"] = state["status"] or 500
        finally:
            duration_ms = (time.perf_counter() - started) * 1000
            _after_request(scope, state["status"], duration_ms, ctx)
            request_context.reset(token)


_VALID_REQUEST_ID = re.compile(rb"^[A-Za-z0-9._:-]{8,64}$")
_QUIET_PREFIXES = ("/assets/", "/favicon")


def _after_request(scope, status, duration_ms: float, ctx: dict) -> None:
    path = scope.get("path", "")
    if path.startswith(_QUIET_PREFIXES):
        return
    method = scope.get("method", "WS")
    api_path = path[4:] if path.startswith("/api/") else path
    access_logger.info(
        "%s %s %s %.1fms", method, path, status if status is not None else "-", duration_ms,
        extra={"fields": {"method": method, "path": path, "status": status,
                          "duration_ms": round(duration_ms, 1),
                          "client": (scope.get("client") or ("-",))[0]}},
    )
    if scope["type"] == "http" and path != "/index.html":
        _latency_samples.append((api_path, duration_ms, method, datetime.now(timezone.utc).isoformat()))


_latency_samples: deque = deque(maxlen=50_000)  # bounded even if flushing stops


def flush_latency_samples() -> int:
    """Save buffered API latency samples (called periodically by the maintenance task)."""
    batch = []
    while _latency_samples:
        try:
            path, ms, method, at = _latency_samples.popleft()
        except IndexError:
            break
        batch.append(("api_latency", path, ms, method, at))
    if batch:
        record_metrics_batch(DB_PATH, batch)
    return len(batch)
