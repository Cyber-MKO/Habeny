"""
How the app reaches LXC.

direct: this process talks to LXC itself (python-lxc and lxc-attach); needs root.
helper: an unprivileged process asks the root helper (app.helper.server) over a
        Unix socket, which only performs a fixed, validated set of operations.

HABENY_LXC_BACKEND=direct|helper; default: direct when running as root, else helper.
Everything else in the app uses `lxc`, `attach_run`, `open_console` and
`read_container_config` from here and never imports python-lxc or runs lxc-attach itself.
"""
import fcntl
import os
import pty
import struct
import subprocess
import termios

from app import config

MODE = config.get("HABENY_LXC_BACKEND") or ("direct" if os.geteuid() == 0 else "helper")

if MODE == "direct":
    import lxc  # noqa: F401  (python-lxc)
elif MODE == "helper":
    from app.helper import client as lxc  # noqa: F401  (same API, via the helper)
else:
    raise RuntimeError(f"Unknown HABENY_LXC_BACKEND: {MODE!r} (use 'direct' or 'helper')")


def attach_run(name: str, argv: list, env: dict | None = None, input_bytes: bytes | None = None,
               timeout: int = 300) -> dict:
    """Run argv inside a container. Returns returncode, stdout, stderr (text), timed_out."""
    if MODE == "helper":
        return lxc.attach_run(name, argv, env=env, input_bytes=input_bytes, timeout=timeout)
    cmd = ["lxc-attach", "-n", name]
    for key, value in (env or {}).items():
        cmd += ["-v", f"{key}={value}"]
    cmd += ["--"] + list(argv)
    try:
        proc = subprocess.run(cmd, input=input_bytes, capture_output=True, timeout=timeout,
                              stdin=None if input_bytes is not None else subprocess.DEVNULL)
        return {"returncode": proc.returncode, "stdout": proc.stdout.decode(errors="replace"),
                "stderr": proc.stderr.decode(errors="replace"), "timed_out": False}
    except subprocess.TimeoutExpired as e:
        return {"returncode": -1, "stdout": (e.stdout or b"").decode(errors="replace"),
                "stderr": f"timeout after {timeout}s", "timed_out": True}


def open_console(name: str, cols: int = 80, rows: int = 24) -> int:
    """PTY master fd of an interactive login shell in the container. Closing it ends the session."""
    if MODE == "helper":
        return lxc.open_console(name, cols, rows)
    master_fd, slave_fd = pty.openpty()
    fcntl.ioctl(master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def set_controlling_tty():
        # In the child after setsid(): make the PTY slave the controlling terminal, so the
        # shell binds to the websocket PTY instead of the server's own terminal
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)

    env = {**os.environ, "TERM": "xterm-256color"}
    try:
        process = subprocess.Popen(["lxc-attach", "-n", name, "--", "/bin/bash", "-l"],
                                   stdin=slave_fd, stdout=slave_fd, stderr=slave_fd, env=env, close_fds=True,
                                   start_new_session=True, preexec_fn=set_controlling_tty)
    finally:
        os.close(slave_fd)
    import threading
    threading.Thread(target=process.wait, daemon=True).start()  # reap when the session ends
    return master_fd


def read_container_config(name: str) -> str | None:
    if MODE == "helper":
        return lxc.read_container_config(name)
    try:
        with open(lxc.Container(name).config_file_name, errors="replace") as f:
            return f.read(1 << 20)
    except OSError:
        return None


def has_lxc_access() -> bool:
    """Whether container operations can work: as root directly, or via the helper."""
    return MODE == "helper" or os.geteuid() == 0
