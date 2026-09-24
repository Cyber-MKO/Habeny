"""
Other Habeny servers (hosts): register them (admins), see them all, and use one from this
console. The UI sends a host's API calls to /hosts/{id}/api/... and its WebSockets to
/hosts/{id}/ws/...; they're relayed with the host's API token.
"""
import asyncio
import contextlib
import ssl
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.logging_config import current_request_id
from app.models import APIResponse
from app.services import hosts as svc
from app.services import tenancy
from app.services.activity import log_activity
from app.services.auth import current_user, require_admin

router = APIRouter()
admin = Depends(require_admin)


class HostRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64, pattern=r"^[\w .-]+$")
    url: str = Field("", max_length=300)
    token: str = Field("", max_length=200)  # an API token created on that host
    fingerprint: str | None = Field(None, max_length=120)
    team_id: int | None = None  # None: every user; else that team (and admins)


def _public(host: dict) -> dict:
    return {k: host.get(k) for k in ("id", "name", "url", "fingerprint", "team_id", "created_at", "last_checked_at",
                                     "last_status", "last_error", "version", "token_hint")}


def _usable(host_id: int, user: dict | None) -> dict:
    host = svc.get_host(host_id, reveal=True)
    if host is None or not svc.usable_by(host, user):
        raise HTTPException(status_code=404, detail="Host not found")
    return host


@router.get("/hosts", response_model=APIResponse)
async def list_hosts(user: dict | None = Depends(current_user)):
    """The hosts you can use (all for admins)."""
    hosts = [_public(h) for h in await asyncio.to_thread(svc.list_hosts) if svc.usable_by(h, user)]
    return APIResponse(success=True, message=f"{len(hosts)} hosts", data={"hosts": hosts})


@router.get("/hosts/overview", response_model=APIResponse)
async def hosts_overview(user: dict | None = Depends(current_user)):
    """Every usable host's status, version, containers and alerts, fetched in parallel."""
    hosts = [h for h in await asyncio.to_thread(svc.list_hosts, True) if svc.usable_by(h, user)]
    results = await asyncio.gather(*(asyncio.to_thread(svc.overview, h) for h in hosts))
    return APIResponse(success=True, message="Hosts overview", data={
        "hosts": [{**_public(h), **r} for h, r in zip(hosts, results, strict=True)]})


@router.post("/hosts", response_model=APIResponse, dependencies=[admin])
async def add_host(body: HostRequest):
    if not body.url or not body.token:
        raise HTTPException(status_code=400, detail="url and token are required")
    if body.team_id is not None and tenancy.get_team(body.team_id) is None:
        raise HTTPException(status_code=404, detail="Team not found")
    try:
        host = await asyncio.to_thread(svc.add_host, body.name.strip(), body.url, body.token, body.fingerprint,
                                       body.team_id)
    except svc.FingerprintNeeded as e:
        # Not an error to the UI: it shows the fingerprint and asks the admin to confirm it
        return APIResponse(success=False, message=str(e), error="fingerprint_needed",
                           data={"fingerprint": e.fingerprint})
    except svc.HostError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    log_activity("host_added", {"host": host["name"], "url": host["url"], "pinned": bool(host["fingerprint"]),
                                "remote_role": host["remote_role"]})
    return APIResponse(success=True, message=f"Host '{host['name']}' added (Habeny {host['version']}; the token is a "
                       f"{host['remote_role']} there)", data={"host": _public(host)})


@router.put("/hosts/{host_id}", response_model=APIResponse, dependencies=[admin])
async def edit_host(host_id: int, body: HostRequest):
    try:
        host = await asyncio.to_thread(svc.update_host, host_id, body.name.strip(), body.team_id, body.token or None,
                                       body.fingerprint)
    except svc.HostError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    if host is None:
        raise HTTPException(status_code=404, detail="Host not found")
    log_activity("host_updated", {"host": host["name"], "token_changed": bool(body.token)})
    return APIResponse(success=True, message=f"Host '{host['name']}' saved", data={"host": _public(host)})


@router.delete("/hosts/{host_id}", response_model=APIResponse, dependencies=[admin])
async def remove_host(host_id: int):
    host = await asyncio.to_thread(svc.delete_host, host_id)
    if host is None:
        raise HTTPException(status_code=404, detail="Host not found")
    log_activity("host_removed", {"host": host["name"]})
    return APIResponse(success=True, message=f"Host '{host['name']}' removed. Revoke its token on that server too.")


# ── relaying ────────────────────────────────────────────────────────────

_RELAYED_REQUEST_HEADERS = ("content-type", "accept")
_RELAYED_RESPONSE_HEADERS = ("content-type", "content-disposition", "retry-after")


@router.api_route("/hosts/{host_id}/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                  include_in_schema=False)
async def relay(host_id: int, path: str, request: Request, user: dict | None = Depends(current_user)):
    """Forward an API call to the host. Your role here already allowed the method (router-wide
    check); the host applies its token's role and teams on top."""
    host = _usable(host_id, user)
    if path.strip("/").startswith(svc.LOCAL_ONLY):
        raise HTTPException(status_code=403, detail="Accounts, tokens, teams and hosts are managed on each server itself")
    body = await request.body()
    headers = {k: v for k, v in request.headers.items() if k.lower() in _RELAYED_REQUEST_HEADERS}
    request_id = current_request_id()
    if request_id:  # the same ID in both servers' logs
        headers["X-Request-ID"] = request_id
    try:
        status, resp_headers, data = await asyncio.to_thread(
            svc.call, host["url"], host["token"], host["fingerprint"], request.method, path,
            request.url.query, body or None, headers)
    except svc.HostError as e:
        raise HTTPException(status_code=502, detail=f"Host {host['name']}: {e}") from None
    if status == 401:  # the host rejected our token: not the same as the user's session expiring here
        status = 502
        data = b'{"detail": "The host rejected this console\'s API token (revoked or expired?). An admin can replace it on the Hosts page."}'
        resp_headers["content-type"] = "application/json"
    out = {k: v for k, v in resp_headers.items() if k in _RELAYED_RESPONSE_HEADERS}
    if "x-request-id" in resp_headers:
        out["X-Remote-Request-ID"] = resp_headers["x-request-id"]
    return Response(content=data, status_code=status, headers=out)


@router.websocket("/hosts/{host_id}/ws/{path:path}")
async def relay_websocket(websocket: WebSocket, host_id: int, path: str):
    """Relay a WebSocket (live metrics, container console) to the host."""
    from websockets.asyncio.client import connect
    from websockets.exceptions import ConnectionClosed

    user = current_user(websocket)
    host = svc.get_host(host_id, reveal=True)
    await websocket.accept()
    if host is None or not svc.usable_by(host, user):
        await websocket.close(code=1008, reason="Host not found")
        return
    parts = urlsplit(host["url"])
    scheme = "wss" if parts.scheme == "https" else "ws"
    context = None
    if scheme == "wss":
        context = ssl.create_default_context()
        if host["fingerprint"]:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE  # replaced by the fingerprint check below
    query = f"?{websocket.url.query}" if websocket.url.query else ""
    try:
        remote = await connect(f"{scheme}://{parts.netloc}/api/ws/{path}{query}", ssl=context, open_timeout=10,
                               additional_headers={"Authorization": f"Bearer {host['token']}"}, proxy=None)
    except Exception as e:
        await websocket.send_text(f"ERROR: can't reach host {host['name']}: {e}\n")
        await websocket.close(code=1011)
        return
    if host["fingerprint"]:
        der = remote.transport.get_extra_info("ssl_object").getpeercert(binary_form=True)
        if svc._fingerprint(der) != host["fingerprint"]:
            await remote.close()
            await websocket.close(code=1008, reason="Host certificate changed")
            return

    async def upstream():
        with contextlib.suppress(Exception):
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    break
                await remote.send(message["bytes"] if message.get("bytes") is not None else message.get("text", ""))
        await remote.close()

    async def downstream():
        with contextlib.suppress(ConnectionClosed, RuntimeError):
            async for message in remote:
                if isinstance(message, bytes):
                    await websocket.send_bytes(message)
                else:
                    await websocket.send_text(message)
        with contextlib.suppress(Exception):
            await websocket.close()

    await asyncio.gather(upstream(), downstream())
