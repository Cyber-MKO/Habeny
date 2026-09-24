"""
One Habeny per data directory: a second instance is refused with a clear message, and
forked workers don't keep the lock alive.
"""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _start(data_dir: Path, hold: bool) -> subprocess.Popen:
    code = textwrap.dedent(f"""
        import sys, time
        from app.services import instance
        try:
            instance.acquire()
        except instance.AlreadyRunning as e:
            print("REFUSED", e, flush=True); sys.exit(3)
        print("LOCKED", flush=True)
        time.sleep({30 if hold else 0})
    """)
    env = {**os.environ, "HABENY_DATA_DIR": str(data_dir)}
    return subprocess.Popen([sys.executable, "-c", code], cwd=ROOT, env=env, stdout=subprocess.PIPE, text=True)


def test_second_instance_is_refused(tmp_path):
    first = _start(tmp_path, hold=True)
    assert first.stdout.readline().strip() == "LOCKED"
    try:
        second = _start(tmp_path, hold=False)
        out, _ = second.communicate(timeout=30)
        assert second.returncode == 3
        assert f"pid {first.pid}" in out and str(tmp_path) in out
        # the CLI sees it as running too (restore/downgrade refuse without --force)
        from app.services import instance
        lock_file = instance.LOCK_FILE
        instance.LOCK_FILE = tmp_path / "habeny.lock"
        try:
            assert instance.running_pid() == first.pid
        finally:
            instance.LOCK_FILE = lock_file
    finally:
        first.kill()
        first.wait()
    # once it's gone, a new one starts
    third = _start(tmp_path, hold=False)
    assert third.communicate(timeout=30)[0].strip() == "LOCKED"


def test_forked_worker_releases_its_copy(tmp_path):
    code = textwrap.dedent("""
        import os, sys, time
        from app.services import instance, lifecycle
        instance.acquire()
        pid = os.fork()
        if pid == 0:                      # a deploy worker
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, 1)
            os.dup2(devnull, 2)           # don't hold the test's output pipe open
            lifecycle.ignore_stop_signals()
            time.sleep(30)
            os._exit(0)
        print(pid, flush=True)
        os._exit(0)                       # the main process dies; the worker lives on
    """)
    env = {**os.environ, "HABENY_DATA_DIR": str(tmp_path)}
    main = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
    worker = int(main.stdout.strip())
    try:
        again = _start(tmp_path, hold=False)
        assert again.communicate(timeout=30)[0].strip() == "LOCKED"  # not blocked by the orphaned worker
    finally:
        os.kill(worker, 9)
