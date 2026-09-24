"""
Privileged LXC helper: the only part of Habeny that runs as root.

It listens on a Unix socket (group-accessible by the service user only, and every
connection's peer uid is checked) and performs a fixed list of LXC operations. Each
argument is validated: container names, config keys (only the macvlan settings the
app uses; never hooks, mounts or other keys that could run host commands), cgroup
keys/values, and create() only with the platform's OS images.

`attach` runs a command inside a container as its root user; that is the app's
purpose, but it is limited to containers and never runs anything on the host.

Run as root (system Python with python3-lxc; only the standard library is needed):
    python3 -m app.helper.server
Environment:
    HABENY_HELPER_SOCKET  socket path (default /run/habeny/helper.sock)
    HABENY_HELPER_USER    user allowed to connect besides root (default "habeny")
"""
import base64
import fcntl
import grp
import logging
import os
import pty
import pwd
import re
import socket
import socketserver
import struct
import subprocess
import termios
import threading

import lxc

from app.core.os_images import OS_IMAGES
from app.core.validation import validate_container_name
from app.helper.protocol import DEFAULT_SOCKET, recv_message, send_message

logger = logging.getLogger("habeny.helper")

ATTACH_BIN = os.environ.get("HABENY_LXC_ATTACH", "lxc-attach")
MAX_TIMEOUT = 3600
STATES = {"RUNNING", "STOPPED", "FROZEN"}
READ_CGROUP_KEYS = {"memory.stat", "memory.usage_in_bytes", "memory.limit_in_bytes",
                    "memory.memsw.usage_in_bytes", "cpu.stat", "pids.current"}
WRITE_CGROUP_KEYS = {"memory.max", "cpu.shares"}
_IFACE = re.compile(r"^[A-Za-z0-9_.:-]{1,15}$")
_MAC = re.compile(r"^([0-9a-f]{2}:){5}[0-9a-f]{2}$")
_ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
# The only config changes the app makes (macvlan networking for OSSEC). Anything
# else, e.g. lxc.hook.* or lxc.mount.*, could run commands or expose the host.
CONFIG_VALUES = {
    "lxc.net.0.type": lambda v: v == "macvlan",
    "lxc.net.0.macvlan.mode": lambda v: v == "bridge",
    "lxc.net.0.link": lambda v: bool(_IFACE.fullmatch(v)),
    "lxc.net.0.flags": lambda v: v == "up",
    "lxc.net.0.hwaddr": lambda v: bool(_MAC.fullmatch(v)),
}
CLEARABLE_CONFIG_KEYS = {"lxc.net.0"}
ALLOWED_IMAGES = [dict(dist=i["distro"], release=i["release"], arch=i["arch"]) for i in OS_IMAGES.values()]


class Refused(ValueError):
    """A request outside what the helper allows."""


def _require(cond: bool, message: str) -> None:
    if not cond:
        raise Refused(message)


def _int(value, lo: int, hi: int, what: str) -> int:
    _require(isinstance(value, int) and not isinstance(value, bool) and lo <= value <= hi, f"invalid {what}")
    return value


def _container(name) -> "lxc.Container":
    try:
        validate_container_name(name)
    except ValueError as e:
        raise Refused(str(e)) from None
    return lxc.Container(name)


def _jsonable(value):
    if isinstance(value, tuple):
        return [_jsonable(v) for v in value]
    return value


# ── operations ──────────────────────────────────────────────────────────

def op_info(req):
    version = getattr(lxc, "version", None)
    path = getattr(lxc, "default_config_path", None)
    return {"version": version() if callable(version) else version,
            "default_config_path": path() if callable(path) else path}


def op_list_containers(req):
    active = req.get("active", True)
    defined = req.get("defined", True)
    _require(isinstance(active, bool) and isinstance(defined, bool), "invalid list flags")
    if active and defined:  # the default; plain call works across python-lxc versions
        return list(lxc.list_containers())
    return list(lxc.list_containers(active=active, defined=defined))


def op_container_get(req):
    attr = req.get("attr")
    _require(attr in ("state", "running", "init_pid", "defined"), "attribute not allowed")
    return getattr(_container(req.get("name")), attr)


def _call_args(method, args):
    _require(isinstance(args, list), "args must be a list")
    if method in ("start", "stop", "destroy", "save_config", "get_ips", "get_interfaces"):
        _require(args == [], f"{method} takes no arguments")
    elif method == "shutdown":
        _require(len(args) == 1, "shutdown(timeout)")
        _int(args[0], 0, MAX_TIMEOUT, "timeout")
    elif method == "wait":
        _require(len(args) == 2 and args[0] in STATES, "wait(state, timeout)")
        _int(args[1], 0, MAX_TIMEOUT, "timeout")
    elif method == "get_cgroup_item":
        _require(len(args) == 1 and args[0] in READ_CGROUP_KEYS, "cgroup key not allowed")
    elif method == "set_cgroup_item":
        _require(len(args) == 2 and args[0] in WRITE_CGROUP_KEYS, "cgroup key not allowed")
        _require(isinstance(args[1], str) and (args[1].isdigit() or args[1] == "max") and len(args[1]) <= 20,
                 "cgroup value must be a number")
    elif method == "clear_config_item":
        _require(len(args) == 1 and args[0] in CLEARABLE_CONFIG_KEYS, "config key not allowed")
    elif method == "set_config_item":
        _require(len(args) == 2 and isinstance(args[1], str) and args[0] in CONFIG_VALUES
                 and CONFIG_VALUES[args[0]](args[1]), "config key/value not allowed")
    elif method == "create":
        _require(len(args) == 3 and args[0] == "download" and args[1] == 0
                 and args[2] in ALLOWED_IMAGES, "only the platform's OS images can be created")
    else:
        raise Refused(f"method not allowed: {method}")


def op_container_call(req):
    method, args = req.get("method"), req.get("args", [])
    _call_args(method, args)
    container = _container(req.get("name"))
    if method == "create":
        # The download template needs network access and can take minutes
        return container.create(args[0], args[1], args[2])
    return _jsonable(getattr(container, method)(*args))


def op_read_config(req):
    container = _container(req.get("name"))
    path = container.config_file_name
    try:
        with open(path, "r", errors="replace") as f:
            return f.read(1 << 20)
    except FileNotFoundError:
        return None


def _attach_argv(req) -> list:
    name = req.get("name")
    _container(name)  # validates
    argv = req.get("argv")
    _require(isinstance(argv, list) and 0 < len(argv) <= 256
             and all(isinstance(a, str) and "\0" not in a for a in argv), "invalid argv")
    env = req.get("env") or {}
    _require(isinstance(env, dict) and all(isinstance(k, str) and _ENV_KEY.fullmatch(k) and isinstance(v, str)
                                           and "\0" not in v for k, v in env.items()), "invalid env")
    cmd = [ATTACH_BIN, "-n", name]
    for key, value in env.items():
        cmd += ["-v", f"{key}={value}"]
    return cmd + ["--"] + argv


def op_attach(req):
    """Run a command inside a container (as the container's root) and return its output."""
    cmd = _attach_argv(req)
    timeout = _int(req.get("run_timeout", 300), 1, MAX_TIMEOUT, "timeout")
    stdin = base64.b64decode(req["input_b64"]) if req.get("input_b64") else None
    try:
        proc = subprocess.run(cmd, input=stdin, capture_output=True, timeout=timeout,
                              stdin=None if stdin is not None else subprocess.DEVNULL)
        return {"returncode": proc.returncode, "stdout": proc.stdout.decode(errors="replace"),
                "stderr": proc.stderr.decode(errors="replace"), "timed_out": False}
    except subprocess.TimeoutExpired as e:
        return {"returncode": -1, "stdout": (e.stdout or b"").decode(errors="replace"),
                "stderr": f"timeout after {timeout}s", "timed_out": True}


def op_console(req):
    """Start an interactive login shell in a container on a new PTY; the PTY master fd
    is handed to the client, which owns the session from then on."""
    cmd = _attach_argv({**req, "argv": ["/bin/bash", "-l"], "env": {}})
    cols = _int(req.get("cols", 80), 1, 1000, "cols")
    rows = _int(req.get("rows", 24), 1, 1000, "rows")
    master_fd, slave_fd = pty.openpty()
    fcntl.ioctl(master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    env = {"PATH": os.environ.get("PATH", "/usr/sbin:/usr/bin:/sbin:/bin"), "TERM": "xterm-256color"}

    def set_controlling_tty():
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)

    try:
        process = subprocess.Popen(cmd, stdin=slave_fd, stdout=slave_fd, stderr=slave_fd, env=env,
                                   close_fds=True, start_new_session=True, preexec_fn=set_controlling_tty)
    finally:
        os.close(slave_fd)
    # Reap the session when the client hangs up (closing the PTY ends the shell)
    threading.Thread(target=process.wait, daemon=True).start()
    return {"pid": process.pid}, master_fd


OPS = {
    "info": op_info,
    "list_containers": op_list_containers,
    "container_get": op_container_get,
    "container_call": op_container_call,
    "read_config": op_read_config,
    "attach": op_attach,
}


# ── server ──────────────────────────────────────────────────────────────

def allowed_uids() -> set:
    uids = {0}
    user = os.environ.get("HABENY_HELPER_USER", "habeny")
    try:
        uids.add(pwd.getpwnam(user).pw_uid)
    except KeyError:
        logger.warning(f"Helper user '{user}' does not exist; only root may connect")
    return uids


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        sock = self.request
        pid, uid, gid = struct.unpack("3i", sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))
        if uid not in self.server.allowed_uids:
            logger.warning(f"Refused connection from uid {uid} (pid {pid})")
            return
        try:
            req, _ = recv_message(sock)
            op = req.get("op") if isinstance(req, dict) else None
            if op == "console":
                result, fd = op_console(req)
                try:
                    send_message(sock, {"ok": True, "result": result}, fds=(fd,))
                finally:
                    os.close(fd)
                return
            if op not in OPS:
                raise Refused(f"unknown operation: {op}")
            logger.debug(f"{op} {req.get('name', '')} {req.get('method', req.get('attr', ''))} (uid {uid})")
            send_message(sock, {"ok": True, "result": OPS[op](req)})
        except Refused as e:
            logger.warning(f"Refused {req.get('op') if isinstance(req, dict) else '?'} from uid {uid}: {e}")
            send_message(sock, {"ok": False, "kind": "refused", "error": str(e)})
        except Exception as e:  # report, don't crash the helper
            logger.exception("Helper operation failed")
            try:
                send_message(sock, {"ok": False, "kind": "error", "error": f"{type(e).__name__}: {e}"})
            except OSError:
                pass


class HelperServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True

    def __init__(self, path: str, uids: set):
        self.allowed_uids = uids
        super().__init__(path, Handler)


def serve(path: str = None, group: str = None) -> HelperServer:
    path = path or os.environ.get("HABENY_HELPER_SOCKET", DEFAULT_SOCKET)
    if os.path.exists(path):
        os.unlink(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    old_umask = os.umask(0o117)  # socket created as 0660
    try:
        server = HelperServer(path, allowed_uids())
    finally:
        os.umask(old_umask)
    group = group or os.environ.get("HABENY_HELPER_USER", "habeny")
    try:
        os.chown(path, 0, grp.getgrnam(group).gr_gid)
    except (KeyError, PermissionError):
        pass
    logger.info(f"Habeny LXC helper listening on {path} (allowed uids: {sorted(server.allowed_uids)})")
    return server


def main():
    from app import config
    from app.logging_config import configure
    # stdout only (the journal): the log file belongs to the unprivileged web app
    configure(level=os.environ.get("HABENY_HELPER_LOG_LEVEL", "INFO"), fmt=config.get("HABENY_LOG_FORMAT"))
    if os.geteuid() != 0:
        logger.warning("The helper is not running as root; LXC operations will fail")
    serve().serve_forever()


if __name__ == "__main__":
    main()
