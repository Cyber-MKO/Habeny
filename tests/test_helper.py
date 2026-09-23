"""
The privileged LXC helper: what it refuses, who may connect, and the client round trip.
"""
import os
import select
import threading

import pytest

pytest.importorskip("lxc", reason="the helper needs python-lxc (or the test stub)")

from app.helper import client, server  # noqa: E402


@pytest.mark.parametrize("method,args", [
    ("set_config_item", ["lxc.hook.pre-start", "/bin/sh -c 'id > /root/pwned'"]),
    ("set_config_item", ["lxc.mount.entry", "/ mnt none bind 0 0"]),
    ("set_config_item", ["lxc.apparmor.profile", "unconfined"]),
    ("set_config_item", ["lxc.net.0.link", "eth0; reboot"]),
    ("set_config_item", ["lxc.net.0.type", "veth"]),
    ("clear_config_item", ["lxc.apparmor"]),
    ("set_cgroup_item", ["devices.allow", "a *:* rwm"]),
    ("set_cgroup_item", ["memory.max", "1G; reboot"]),
    ("get_cgroup_item", ["../../../etc/shadow"]),
    ("create", ["busybox", 0, {}]),
    ("create", ["download", 0, {"dist": "alpine", "release": "edge", "arch": "amd64"}]),
    ("wait", ["RUNNING", 10 ** 9]),
    ("attach_interface", ["eth0"]),
    ("__class__", []),
])
def test_refuses_anything_outside_the_allowlist(method, args):
    with pytest.raises(server.Refused):
        server._call_args(method, args)


@pytest.mark.parametrize("method,args", [
    ("set_config_item", ["lxc.net.0.link", "enp3s0"]),
    ("set_config_item", ["lxc.net.0.hwaddr", "00:16:3e:12:34:56"]),
    ("set_cgroup_item", ["memory.max", "536870912"]),
    ("create", ["download", 0, {"dist": "ubuntu", "release": "jammy", "arch": "amd64"}]),
    ("wait", ["STOPPED", 10]),
    ("get_ips", []),
])
def test_allows_what_the_app_uses(method, args):
    server._call_args(method, args)


@pytest.mark.parametrize("req", [
    {"name": "../../etc", "argv": ["id"]},
    {"name": "-rf", "argv": ["id"]},
    {"name": "c1", "argv": []},
    {"name": "c1", "argv": ["id"], "env": {"BAD KEY": "x"}},
    {"name": "c1", "argv": ["a\0b"]},
])
def test_attach_request_validation(req):
    with pytest.raises(server.Refused):
        server._attach_argv(req)


@pytest.fixture()
def helper(tmp_path, monkeypatch):
    """A helper on a temp socket that runs "lxc-attach" as a local stand-in."""
    fake = tmp_path / "lxc-attach"
    fake.write_text('#!/bin/bash\nwhile [ $# -gt 0 ]; do case "$1" in -n) shift 2;; -v) export "$2"; shift 2;;'
                    ' --) shift; break;; *) shift;; esac; done\nexec "$@"\n')
    fake.chmod(0o755)
    monkeypatch.setattr(server, "ATTACH_BIN", str(fake))
    path = str(tmp_path / "helper.sock")
    srv = server.HelperServer(path, {os.geteuid()})
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("HABENY_HELPER_SOCKET", path)
    yield srv
    srv.shutdown()
    srv.server_close()


def test_client_round_trip(helper):
    result = client.attach_run("c1", ["bash", "-c", 'cat; echo "env=$GREETING"'], env={"GREETING": "hi"},
                               input_bytes=b"from stdin\n", timeout=10)
    assert result["returncode"] == 0
    assert result["stdout"] == "from stdin\nenv=hi\n"
    with pytest.raises(ValueError, match="refused"):
        client.Container("c1").set_config_item("lxc.hook.pre-start", "/bin/true")


def test_console_passes_a_working_pty(helper, monkeypatch):
    monkeypatch.setattr(server, "_attach_argv", lambda req: ["/bin/bash", "--norc", "-i"])
    fd = client.open_console("c1", 100, 30)
    try:
        os.write(fd, b"echo console-$((40+2))\n")
        out = b""
        while b"console-42" not in out:
            ready, _, _ = select.select([fd], [], [], 5)
            assert ready, f"no output from console; got {out!r}"
            out += os.read(fd, 1024)
        os.write(fd, b"exit\n")
    finally:
        os.close(fd)


def test_other_users_are_refused(helper):
    helper.allowed_uids = {os.geteuid() + 12345}
    with pytest.raises((ConnectionError, client.HelperError)):
        client.attach_run("c1", ["true"], timeout=5)


def test_unreachable_helper_is_reported(monkeypatch, tmp_path):
    monkeypatch.setenv("HABENY_HELPER_SOCKET", str(tmp_path / "missing.sock"))
    with pytest.raises(client.HelperUnavailable, match="is habeny-helper running"):
        client.list_containers()
