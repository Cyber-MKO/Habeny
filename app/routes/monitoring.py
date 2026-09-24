"""
Monitoring: health probes, Prometheus metrics, alerts; notification channels (admins).

- GET /healthz: liveness, no sign-in (for load balancers and systemd watchdogs)
- GET /readyz: whether Habeny can do its job (database, LXC, disk), no sign-in; 503 if not
- GET /metrics: Prometheus text format; needs a sign-in or API token (viewer is enough)
- GET /system/alerts: active alerts
"""
import asyncio
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from app import config
from app.models import APIResponse
from app.services import alerts, lifecycle, notify, telemetry
from app.services.activity import log_activity
from app.services.auth import require_admin
from app.version import __version__

public_router = APIRouter()
router = APIRouter()
admin_router = APIRouter(prefix="/notifications", dependencies=[Depends(require_admin)])


@public_router.get("/healthz", include_in_schema=True)
async def healthz():
    """The process is up and answering."""
    return {"status": "ok", "version": __version__}


def _readiness() -> dict[str, str]:
    checks = {}
    try:
        conn = sqlite3.connect(config.DB_PATH, timeout=5)
        try:
            conn.execute("SELECT 1 FROM users LIMIT 1").fetchall()
        finally:
            conn.close()
        checks["database"] = "ok"
    except sqlite3.Error:
        checks["database"] = "failing"
    lxc_alert = any(a["name"] == "lxc_unavailable" for a in alerts.manager.active())
    checks["lxc"] = "failing" if lxc_alert else "ok"
    threshold = config.get("HABENY_ALERT_DISK_PERCENT")
    disk = telemetry.disk_usage().get("data")
    low = bool(disk and threshold and disk["free"] * 100 / disk["total"] < threshold / 2)
    checks["disk"] = "low" if low else "ok"
    if lifecycle.shutting_down():
        checks["server"] = "shutting down"
    return checks


@public_router.get("/readyz")
async def readyz():
    """Ready for work: database answers, LXC is reachable, data disk isn't nearly full, not stopping.
    Deliberately vague for anonymous callers: details are on /system/alerts."""
    checks = await asyncio.to_thread(_readiness)
    ready = all(v == "ok" for v in checks.values())
    return JSONResponse({"status": "ready" if ready else "not ready", "checks": checks},
                        status_code=200 if ready else 503)


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    """Prometheus metrics (see app/services/telemetry.py for the scrape configuration)."""
    body = await asyncio.to_thread(telemetry.render)
    return PlainTextResponse(body, media_type="text/plain; version=0.0.4; charset=utf-8")


@router.get("/system/alerts", response_model=APIResponse)
async def list_alerts():
    active = alerts.manager.active()
    return APIResponse(success=True, message=f"{len(active)} active alerts", data={"alerts": active})


# ── notification channels (admins) ──────────────────────────────────────

class ChannelRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    type: str = Field("webhook", pattern="^(email|slack|webhook)$")
    config: dict = Field(default_factory=dict)
    events: list[str] = Field(default_factory=list)  # empty: every event
    only_problems: bool = False
    enabled: bool = True


def _bad(e: notify.ChannelError):
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@admin_router.get("/channels", response_model=APIResponse)
async def get_channels():
    channels = await asyncio.to_thread(notify.list_channels)
    return APIResponse(success=True, message=f"{len(channels)} channels", data={
        "channels": channels, "events": notify.EVENTS,
        "email_available": bool(config.get("HABENY_SMTP_HOST")),
    })


@admin_router.post("/channels", response_model=APIResponse)
async def add_channel(body: ChannelRequest):
    try:
        channel = await asyncio.to_thread(notify.create_channel, body.name.strip(), body.type, body.config,
                                          body.events, body.only_problems, body.enabled)
    except notify.ChannelError as e:
        raise _bad(e) from None
    log_activity("notification_channel_created", {"channel": channel["name"], "type": channel["type"],
                                                  "events": channel["events"]})
    return APIResponse(success=True, message=f"Channel '{channel['name']}' added", data={"channel": channel})


@admin_router.put("/channels/{channel_id}", response_model=APIResponse)
async def edit_channel(channel_id: int, body: ChannelRequest):
    try:
        channel = await asyncio.to_thread(notify.update_channel, channel_id, body.name.strip(), body.config,
                                          body.events, body.only_problems, body.enabled)
    except notify.ChannelError as e:
        raise _bad(e) from None
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    log_activity("notification_channel_updated", {"channel": channel["name"], "enabled": channel["enabled"],
                                                  "events": channel["events"]})
    return APIResponse(success=True, message=f"Channel '{channel['name']}' saved", data={"channel": channel})


@admin_router.delete("/channels/{channel_id}", response_model=APIResponse)
async def remove_channel(channel_id: int):
    channel = await asyncio.to_thread(notify.delete_channel, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    log_activity("notification_channel_deleted", {"channel": channel["name"]})
    return APIResponse(success=True, message=f"Channel '{channel['name']}' deleted")


@admin_router.post("/channels/{channel_id}/test", response_model=APIResponse)
async def test_channel(channel_id: int):
    """Send a test message now and report whether it went through."""
    try:
        error = await asyncio.to_thread(notify.send_test, channel_id)
    except notify.ChannelError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    if error:
        return APIResponse(success=False, message=f"The test message failed: {error}", error=error)
    return APIResponse(success=True, message="Test message sent")
