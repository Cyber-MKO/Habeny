"""
Wire format between the web app and the privileged LXC helper: one request and one
response per Unix-socket connection, each a 4-byte big-endian length followed by
JSON. The console response also carries a file descriptor (SCM_RIGHTS).
"""
import json
import socket
import struct
from typing import Any

MAX_MESSAGE = 64 * 1024 * 1024  # install logs can be large; this is a sanity bound
DEFAULT_SOCKET = "/run/habeny/helper.sock"


def send_message(sock: socket.socket, payload: Any, fds: tuple = ()) -> None:
    body = json.dumps(payload).encode()
    data = struct.pack(">I", len(body)) + body
    if fds:
        socket.send_fds(sock, [data], list(fds))
    else:
        sock.sendall(data)


def _recv_exact(sock: socket.socket, n: int, buf: bytes = b"") -> bytes:
    while len(buf) < n:
        chunk = sock.recv(min(n - len(buf), 1 << 20))
        if not chunk:
            raise ConnectionError("helper connection closed mid-message")
        buf += chunk
    return buf


def recv_message(sock: socket.socket, want_fds: int = 0) -> tuple[Any, list[int]]:
    fds: list[int] = []
    if want_fds:
        first, fds, _flags, _addr = socket.recv_fds(sock, 65536, want_fds)
        if not first:
            raise ConnectionError("helper closed the connection")
    else:
        first = b""
    header = _recv_exact(sock, 4, first[:4]) if len(first) < 4 else first[:4]
    (length,) = struct.unpack(">I", header)
    if length > MAX_MESSAGE:
        raise ValueError("message too large")
    body = _recv_exact(sock, length, first[4:])
    return json.loads(body[:length]), fds
