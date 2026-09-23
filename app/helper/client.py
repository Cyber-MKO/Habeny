"""
Client for the privileged LXC helper. Exposes the subset of the python-lxc API the
app uses (list_containers, Container, version, default_config_path), so app code
works unchanged whether it talks to LXC directly (as root) or through the helper.
"""
import base64
import os
import socket
from typing import Any, Optional

from app.helper.protocol import DEFAULT_SOCKET, recv_message, send_message


class HelperError(RuntimeError):
    pass


class HelperUnavailable(HelperError):
    pass


def socket_path() -> str:
    return os.environ.get("HABENY_HELPER_SOCKET", DEFAULT_SOCKET)


def _request(payload: dict, timeout: Optional[float], want_fds: int = 0):
    path = socket_path()
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        try:
            sock.connect(path)
        except (FileNotFoundError, ConnectionRefusedError, PermissionError) as e:
            raise HelperUnavailable(f"LXC helper not reachable at {path} ({e}); is habeny-helper running?") from e
        send_message(sock, payload)
        response, fds = recv_message(sock, want_fds)
    finally:
        sock.close()
    if not isinstance(response, dict):
        raise HelperError("malformed helper response")
    if response.get("ok"):
        return response.get("result"), fds
    for fd in fds:
        os.close(fd)
    if response.get("kind") == "refused":
        raise ValueError(f"LXC helper refused: {response.get('error')}")
    raise HelperError(response.get("error", "helper error"))


def call(op: str, timeout: Optional[float] = 60, **kwargs) -> Any:
    return _request({"op": op, **kwargs}, timeout)[0]


# ── python-lxc compatible surface ───────────────────────────────────────

def list_containers(active: bool = True, defined: bool = True, as_object: bool = False, config_path=None):
    names = call("list_containers", active=active, defined=defined)
    return [Container(n) for n in names] if as_object else names


def __getattr__(attr):  # module-level: lxc.version, lxc.default_config_path
    if attr in ("version", "default_config_path"):
        return call("info")[attr]
    raise AttributeError(attr)


class Container:
    def __init__(self, name: str, config_path=None):
        self.name = name

    def _get(self, attr):
        return call("container_get", name=self.name, attr=attr)

    def _call(self, method, *args, timeout: Optional[float] = 120):
        return call("container_call", timeout=timeout, name=self.name, method=method, args=list(args))

    state = property(lambda self: self._get("state"))
    running = property(lambda self: self._get("running"))
    init_pid = property(lambda self: self._get("init_pid"))
    defined = property(lambda self: self._get("defined"))

    def create(self, template, flags=0, args=None):
        return self._call("create", template, flags, dict(args or {}), timeout=1800)

    def start(self):
        return self._call("start")

    def stop(self):
        return self._call("stop")

    def shutdown(self, timeout=-1):
        return self._call("shutdown", int(timeout), timeout=max(int(timeout), 0) + 60)

    def destroy(self):
        return self._call("destroy")

    def wait(self, state, timeout=-1):
        return self._call("wait", state, int(timeout), timeout=max(int(timeout), 0) + 60)

    def save_config(self):
        return self._call("save_config")

    def get_ips(self, *args, **kwargs):
        return tuple(self._call("get_ips"))

    def get_interfaces(self):
        return tuple(self._call("get_interfaces"))

    def get_cgroup_item(self, key):
        return self._call("get_cgroup_item", key)

    def set_cgroup_item(self, key, value):
        return self._call("set_cgroup_item", key, str(value))

    def set_config_item(self, key, value):
        return self._call("set_config_item", key, str(value))

    def clear_config_item(self, key):
        return self._call("clear_config_item", key)


# ── attach / console / config ───────────────────────────────────────────

def attach_run(name: str, argv: list, env: Optional[dict] = None, input_bytes: Optional[bytes] = None,
               timeout: int = 300) -> dict:
    return call("attach", timeout=timeout + 30, name=name, argv=list(argv), env=env or {},
                input_b64=base64.b64encode(input_bytes).decode() if input_bytes is not None else None,
                run_timeout=int(timeout))


def open_console(name: str, cols: int = 80, rows: int = 24) -> int:
    """Returns the PTY master fd of a login shell in the container (caller closes it)."""
    result, fds = _request({"op": "console", "name": name, "cols": cols, "rows": rows}, timeout=30, want_fds=1)
    if not fds:
        raise HelperError("helper did not return a console")
    return fds[0]


def read_container_config(name: str) -> Optional[str]:
    return call("read_config", name=name)
