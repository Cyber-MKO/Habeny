"""
WebSocket console sessions into running containers.
"""
import asyncio
import fcntl
import json
import os
import pty
import struct
import subprocess
import termios

import lxc
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from utils import validate_container_name

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

    if os.geteuid() != 0:
        await websocket.send_text("WARNING: API is not running as root. Console access may fail.\n")

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

    master_fd, slave_fd = pty.openpty()
    env = os.environ.copy()
    env["TERM"] = "xterm-256color"

    def set_controlling_tty():
        # Runs in the child after setsid(): make the PTY slave (fd 0) the
        # controlling terminal so the shell binds to the websocket PTY
        # instead of the terminal the API server was started from.
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)

    try:
        process = subprocess.Popen(
            ["lxc-attach", "-n", container_name, "--", "/bin/bash", "-l"],
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            env=env,
            close_fds=True,
            start_new_session=True,
            preexec_fn=set_controlling_tty
        )
        os.close(slave_fd)
    except Exception as e:
        try:
            os.close(slave_fd)
        except Exception:
            pass
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

    try:
        process.terminate()
        process.wait(timeout=2)
    except Exception:
        process.kill()

    try:
        os.close(master_fd)
    except Exception:
        pass
