"""
Notifications: email, Slack and webhooks when something finishes or an alert changes.

Admins configure channels (Notifications page, /notifications/channels). Each channel
picks the events it wants and can be limited to problems (warnings and errors).
Delivery runs on a background thread with retries, so a slow or unreachable endpoint
never holds up the work that triggered it.

Webhook payload (POST, JSON): {"event", "level", "title", "text", "fields", "link", "time",
"server": {"host", "version", "url"}}. With a secret set, `X-Habeny-Signature:
sha256=<hex HMAC-SHA256 of the body>` lets the receiver check it came from Habeny.
"""
import contextlib
import hashlib
import hmac
import json
import logging
import queue
import smtplib
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request
from email.message import EmailMessage
from typing import Any

from app import config
from app.core.secrets import decrypt_secret, encrypt_secret
from app.models import utc_now

logger = logging.getLogger(__name__)

EVENTS = {
    "deployment.finished": "A deployment finished",
    "simulation.finished": "A simulation finished",
    "benchmark.finished": "A benchmark finished",
    "alert.firing": "An alert started (low disk space, failed deployment or backup, LXC unavailable)",
    "alert.resolved": "An alert cleared",
}
TYPES = ("email", "slack", "webhook")
SECRET_FIELDS = {"slack": ("url",), "webhook": ("url", "secret")}
PROBLEM_LEVELS = ("warning", "error")
RETRY_DELAYS = (5, 30, 120)  # seconds before each retry


class ChannelError(ValueError):
    pass


# ── storage ─────────────────────────────────────────────────────────────

def _conn():
    import sqlite3
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _row(row, reveal: bool = False) -> dict[str, Any]:
    channel = dict(row)
    channel["events"] = json.loads(channel["events"])
    channel["enabled"] = bool(channel["enabled"])
    channel["only_problems"] = bool(channel["only_problems"])
    settings = json.loads(channel.pop("config"))
    for field in SECRET_FIELDS.get(channel["type"], ()):
        if settings.get(field):
            plain = decrypt_secret(settings[field])
            settings[field] = plain if reveal else _hint(field, plain)
    channel["config"] = settings
    return channel


def _hint(field: str, value: str | None) -> str:
    """Enough to recognise a stored URL or secret without revealing it."""
    if not value:
        return ""
    if field == "url" and "://" in value:
        host = value.split("://", 1)[1].split("/", 1)[0]
        return f"{value.split('://', 1)[0]}://{host}/…"
    return "••••••"


def validate(channel_type: str, settings: dict[str, Any]) -> dict[str, Any]:
    if channel_type not in TYPES:
        raise ChannelError(f"type must be one of {', '.join(TYPES)}")
    if channel_type == "email":
        to = settings.get("to") or []
        if isinstance(to, str):
            to = [a.strip() for a in to.replace(";", ",").split(",") if a.strip()]
        if not to or not all("@" in a and " " not in a and len(a) <= 254 for a in to):
            raise ChannelError("to: one or more email addresses")
        if not config.get("HABENY_SMTP_HOST"):
            raise ChannelError("email needs a mail server: set HABENY_SMTP_HOST (see the administrator guide, Notifications)")
        return {"to": to[:50]}
    url = (settings.get("url") or "").strip()
    if not url.startswith(("https://", "http://")) or len(url) > 2000:
        raise ChannelError("url: an http(s) address")
    cleaned = {"url": url}
    if channel_type == "webhook" and settings.get("secret"):
        cleaned["secret"] = str(settings["secret"])[:200]
    return cleaned


def _store_settings(channel_type: str, settings: dict[str, Any]) -> str:
    stored = dict(settings)
    for field in SECRET_FIELDS.get(channel_type, ()):
        if stored.get(field):
            stored[field] = encrypt_secret(stored[field])
    return json.dumps(stored)


def _check_events(events: list[str]) -> list[str]:
    unknown = [e for e in events if e not in EVENTS]
    if unknown:
        raise ChannelError(f"unknown events: {', '.join(unknown)}")
    return sorted(set(events))


def list_channels() -> list[dict[str, Any]]:
    with contextlib.closing(_conn()) as conn:
        return [_row(r) for r in conn.execute("SELECT * FROM notification_channels ORDER BY name COLLATE NOCASE")]


def get_channel(channel_id: int, reveal: bool = False) -> dict[str, Any] | None:
    with contextlib.closing(_conn()) as conn:
        row = conn.execute("SELECT * FROM notification_channels WHERE id = ?", (channel_id,)).fetchone()
        return _row(row, reveal) if row else None


def create_channel(name: str, channel_type: str, settings: dict, events: list[str], only_problems: bool,
                   enabled: bool = True) -> dict[str, Any]:
    import sqlite3
    cleaned = validate(channel_type, settings)
    now = utc_now().isoformat()
    try:
        with contextlib.closing(_conn()) as conn:
            cur = conn.execute(
                "INSERT INTO notification_channels (name, type, config, events, only_problems, enabled, created_at,"
                " updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (name, channel_type, _store_settings(channel_type, cleaned), json.dumps(_check_events(events)),
                 int(only_problems), int(enabled), now, now))
            conn.commit()
            channel_id = cur.lastrowid
    except sqlite3.IntegrityError:
        raise ChannelError(f"a channel named '{name}' exists") from None
    return get_channel(channel_id)


def update_channel(channel_id: int, name: str, settings: dict, events: list[str], only_problems: bool,
                   enabled: bool) -> dict[str, Any] | None:
    """Secret fields left empty keep their stored value."""
    import sqlite3
    current = get_channel(channel_id, reveal=True)
    if current is None:
        return None
    merged = {**current["config"], **{k: v for k, v in settings.items() if v not in (None, "")}}
    cleaned = validate(current["type"], merged)
    try:
        with contextlib.closing(_conn()) as conn:
            conn.execute(
                "UPDATE notification_channels SET name = ?, config = ?, events = ?, only_problems = ?, enabled = ?,"
                " updated_at = ? WHERE id = ?",
                (name, _store_settings(current["type"], cleaned), json.dumps(_check_events(events)),
                 int(only_problems), int(enabled), utc_now().isoformat(), channel_id))
            conn.commit()
    except sqlite3.IntegrityError:
        raise ChannelError(f"a channel named '{name}' exists") from None
    return get_channel(channel_id)


def delete_channel(channel_id: int) -> dict[str, Any] | None:
    channel = get_channel(channel_id)
    if channel:
        with contextlib.closing(_conn()) as conn:
            conn.execute("DELETE FROM notification_channels WHERE id = ?", (channel_id,))
            conn.commit()
    return channel


def _record_result(channel_id: int, error: str | None) -> None:
    with contextlib.suppress(Exception), contextlib.closing(_conn()) as conn:
        conn.execute("UPDATE notification_channels SET last_sent_at = ?, last_status = ?, last_error = ? WHERE id = ?",
                     (utc_now().isoformat(), "error" if error else "ok", error, channel_id))
        conn.commit()


# ── messages and delivery ───────────────────────────────────────────────

def _message(event: str, level: str, title: str, text: str, fields: dict | None, link: str | None) -> dict:
    from app.version import __version__
    base = config.get("HABENY_PUBLIC_URL").rstrip("/")
    return {
        "event": event, "level": level, "title": title, "text": text, "fields": fields or {},
        "link": f"{base}{link}" if base and link and link.startswith("/") else link,
        "time": utc_now().isoformat(),
        "server": {"host": socket.gethostname(), "version": __version__, "url": base or None},
    }


_ICONS = {"success": ":white_check_mark:", "info": ":information_source:", "warning": ":warning:", "error": ":x:"}


def _plain_text(msg: dict) -> str:
    lines = [msg["text"], ""] if msg["text"] else []
    lines += [f"{k.replace('_', ' ').capitalize()}: {v}" for k, v in msg["fields"].items()]
    if msg["link"]:
        lines += ["", msg["link"]]
    lines += ["", f"— Habeny on {msg['server']['host']}"]
    return "\n".join(lines).strip()


def _post_json(url: str, body: bytes, headers: dict[str, str]) -> None:
    from app.version import __version__
    request = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json", "User-Agent": f"Habeny/{__version__}", **headers})
    try:
        with urllib.request.urlopen(request, timeout=10) as resp:  # noqa: S310 (http(s) only, checked on save)
            resp.read(1024)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} {e.reason}") from None
    except (urllib.error.URLError, OSError) as e:
        raise RuntimeError(str(getattr(e, "reason", e))) from None


def _send_slack(settings: dict, msg: dict) -> None:
    text = f"{_ICONS.get(msg['level'], '')} *{msg['title']}*\n{_plain_text(msg)}"
    _post_json(settings["url"], json.dumps({"text": text}).encode(), {})


def _send_webhook(settings: dict, msg: dict) -> None:
    body = json.dumps(msg).encode()
    headers = {"X-Habeny-Event": msg["event"]}
    if settings.get("secret"):
        digest = hmac.new(settings["secret"].encode(), body, hashlib.sha256).hexdigest()
        headers["X-Habeny-Signature"] = f"sha256={digest}"
    _post_json(settings["url"], body, headers)


def _send_email(settings: dict, msg: dict) -> None:
    host = config.get("HABENY_SMTP_HOST")
    if not host:
        raise RuntimeError("no mail server configured (HABENY_SMTP_HOST)")
    email = EmailMessage()
    email["Subject"] = f"[Habeny] {msg['title']}"
    email["From"] = config.get("HABENY_SMTP_FROM") or f"habeny@{socket.getfqdn()}"
    email["To"] = ", ".join(settings["to"])
    email.set_content(_plain_text(msg))
    port, security = config.get("HABENY_SMTP_PORT"), config.get("HABENY_SMTP_SECURITY")
    context = ssl.create_default_context()
    smtp_class = smtplib.SMTP_SSL if security == "ssl" else smtplib.SMTP
    kwargs = {"context": context} if security == "ssl" else {}
    with smtp_class(host, port, timeout=20, **kwargs) as smtp:
        if security == "starttls":
            smtp.starttls(context=context)
        if config.get("HABENY_SMTP_USER"):
            smtp.login(config.get("HABENY_SMTP_USER"), config.get("HABENY_SMTP_PASSWORD"))
        smtp.send_message(email)


SENDERS = {"email": _send_email, "slack": _send_slack, "webhook": _send_webhook}


def deliver(channel: dict, msg: dict) -> None:
    """Send one message now (raises on failure). `channel` needs its revealed config."""
    SENDERS[channel["type"]](channel["config"], msg)


class _Dispatcher:
    """One background thread; a message is retried a few times before it's given up."""

    def __init__(self):
        self._queue: queue.Queue = queue.Queue(maxsize=1000)
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def submit(self, channel_id: int, msg: dict) -> None:
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="habeny-notify", daemon=True)
                self._thread.start()
        try:
            self._queue.put_nowait((channel_id, msg, 0))
        except queue.Full:
            logger.error("Notification queue full; dropped a notification")

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            try:
                self._handle(*item)
            except Exception:
                logger.exception("Notification delivery crashed")
            finally:
                self._queue.task_done()

    def _handle(self, channel_id: int, msg: dict, attempt: int) -> None:
        from app.services import telemetry
        channel = get_channel(channel_id, reveal=True)
        if channel is None or not channel["enabled"]:
            return
        try:
            deliver(channel, msg)
        except Exception as e:
            if attempt < len(RETRY_DELAYS):
                retry = threading.Timer(RETRY_DELAYS[attempt], self._queue.put, ((channel_id, msg, attempt + 1),))
                retry.daemon = True
                retry.start()
                return
            logger.warning(f"Notification to '{channel['name']}' failed after {attempt + 1} attempts: {e}")
            _record_result(channel_id, str(e)[:500])
            telemetry.NOTIFICATIONS.inc(type=channel["type"], result="failed")
            return
        _record_result(channel_id, None)
        telemetry.NOTIFICATIONS.inc(type=channel["type"], result="sent")

    def wait_idle(self, timeout: float = 5) -> None:
        """Tests: wait until queued messages were handled."""
        deadline = time.monotonic() + timeout
        while self._queue.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.05)


dispatcher = _Dispatcher()


def emit(event: str, title: str, text: str = "", level: str = "info", fields: dict | None = None,
         link: str | None = None) -> int:
    """Queue a notification for every enabled channel that wants it. Returns how many."""
    if event not in EVENTS:
        raise ValueError(f"unknown event {event}")
    try:
        channels = [c for c in list_channels() if c["enabled"]
                    and (not c["events"] or event in c["events"])
                    and (not c["only_problems"] or level in PROBLEM_LEVELS)]
    except Exception as e:  # e.g. the table doesn't exist yet: never break the caller
        logger.error(f"Couldn't load notification channels: {e}")
        return 0
    msg = _message(event, level, title, text, fields, link)
    for channel in channels:
        dispatcher.submit(channel["id"], msg)
    return len(channels)


def send_test(channel_id: int) -> str | None:
    """Send a test message now. Returns the error, or None when it went through."""
    channel = get_channel(channel_id, reveal=True)
    if channel is None:
        raise ChannelError("channel not found")
    msg = _message("test", "info", "Test notification",
                   f"Channel '{channel['name']}' is set up correctly.", {"channel": channel["name"]}, "/notifications")
    try:
        deliver(channel, msg)
    except Exception as e:
        _record_result(channel_id, str(e)[:500])
        return str(e)
    _record_result(channel_id, None)
    return None
