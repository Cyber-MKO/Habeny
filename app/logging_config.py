"""
Logging: one setup for the app, uvicorn and the helper.

- Every log line carries the request ID (and user) of the request it belongs to, so a
  problem can be followed through the logs; the same ID is returned to the client in
  the X-Request-ID header and in error responses.
- HABENY_LOG_FORMAT: `text` (default) or `json` (one object per line, for log shippers).
- Always to stdout (journald under systemd, which rotates it); HABENY_LOG_FILE adds a
  file, rotated at HABENY_LOG_MAX_MB with HABENY_LOG_BACKUPS old files kept.
"""
import json
import logging
import logging.handlers
import sys
import traceback
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Mutable per-request record: set at the edge, filled in further down (the user is only
# known after authentication), read by the log filter and the access log
request_context: ContextVar[dict | None] = ContextVar("habeny_request", default=None)


def current_request_id() -> str | None:
    ctx = request_context.get()
    return ctx["id"] if ctx else None


def set_request_user(username: str) -> None:
    ctx = request_context.get()
    if ctx is not None:
        ctx["user"] = username


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        ctx = request_context.get()
        record.request_id = ctx["id"] if ctx else "-"
        record.user = (ctx.get("user") if ctx else None) or "-"
        return True


TEXT_FORMAT = "%(asctime)s %(levelname)-7s %(name)s [%(request_id)s] %(message)s"


class JsonFormatter(logging.Formatter):
    """One JSON object per line. Extra structured fields: logger.info(msg, extra={"fields": {...}})."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        if getattr(record, "request_id", "-") != "-":
            entry["request_id"] = record.request_id
        if getattr(record, "user", "-") != "-":
            entry["user"] = record.user
        entry.update(getattr(record, "fields", None) or {})
        if record.exc_info:
            entry["exception"] = "".join(traceback.format_exception(*record.exc_info)).rstrip()
        return json.dumps(entry, default=str)


def configure(level: str = "info", fmt: str = "text", log_file: str = "", max_mb: int = 50,
              backups: int = 5) -> None:
    formatter = JsonFormatter() if fmt == "json" else logging.Formatter(TEXT_FORMAT)
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.handlers.RotatingFileHandler(
            log_file, maxBytes=max_mb * 1024 * 1024, backupCount=backups, encoding="utf-8"))
    context = ContextFilter()
    for handler in handlers:
        handler.setFormatter(formatter)
        handler.addFilter(context)

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    for handler in handlers:
        root.addHandler(handler)
    root.setLevel(level.upper())

    # uvicorn: same handlers and format; its access log is replaced by ours (with request IDs)
    for name in ("uvicorn", "uvicorn.error"):
        uv = logging.getLogger(name)
        uv.handlers.clear()
        uv.propagate = True
    access = logging.getLogger("uvicorn.access")
    access.handlers.clear()
    access.propagate = False
    access.disabled = True


def configure_from_settings() -> None:
    from app import config
    configure(
        level=config.get("HABENY_LOG_LEVEL"),
        fmt=config.get("HABENY_LOG_FORMAT"),
        log_file=config.get("HABENY_LOG_FILE"),
        max_mb=config.get("HABENY_LOG_MAX_MB"),
        backups=config.get("HABENY_LOG_BACKUPS"),
    )
