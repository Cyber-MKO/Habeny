"""
WebSocket console sessions into running containers.
"""
import asyncio
import contextlib
import fcntl
import json
import os
import struct
import termios

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.container import validate_container_name
from app.core.lxc_backend import lxc, open_console

router = APIRouter()


def resize_pty(fd: int, cols: int, rows: int) -> None:
    """Resize a pseudo-terminal for interactive console sessions."""
    if cols <= 0 or rows <= 0:
        return
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


@router.websocket("/ws/console/{container_name}")
async def console_session(websocket: WebSocket, container_name: str):
    """WebSocket console session into a running container."""
    await websocket.accept()

    if not validate_container_name(container_name):
        await websocket.send_text("ERROR: Invalid container name.\n")
        await websocket.close(code=1008)
        return

    if container_name not in lxc.list_containers():
        await websocket.send_text("ERROR: Container not found.\n")
        await websocket.close(code=1008)
        return

    container = lxc.Container(container_name)
    if not container.running:
        await websocket.send_text("ERROR: Container is not running.\n")
        await websocket.close(code=1008)
        return

    try:
        master_fd = await asyncio.to_thread(open_console, container_name, 80, 24)
    except Exception as e:
        await websocket.send_text(f"ERROR: Failed to start console: {e}\n")
        await websocket.close(code=1011)
        return

    resize_pty(master_fd, 80, 24)

    async def read_pty():
        try:
            while True:
                data = await asyncio.to_thread(os.read, master_fd, 1024)
                if not data:
                    break
                await websocket.send_text(data.decode(errors="ignore"))
        except Exception:
            pass

    async def write_pty():
        try:
            while True:
                message = await websocket.receive_text()
                if not message:
                    continue
                if message.startswith("{"):
                    try:
                        payload = json.loads(message)
                    except json.JSONDecodeError:
                        payload = None
                    if payload and payload.get("type") == "resize":
                        cols = int(payload.get("cols", 0))
                        rows = int(payload.get("rows", 0))
                        resize_pty(master_fd, cols, rows)
                        continue
                os.write(master_fd, message.encode())
        except WebSocketDisconnect:
            pass
        except Exception:
            pass

    reader = asyncio.create_task(read_pty())
    writer = asyncio.create_task(write_pty())
    done, pending = await asyncio.wait({reader, writer}, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()

    # Closing the PTY hangs up the session; the shell exits and is reaped by its parent
    with contextlib.suppress(OSError):
        os.close(master_fd)
