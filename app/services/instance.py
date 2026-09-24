"""
One Habeny per data directory. Habeny keeps live state in its process (running jobs,
sessions' caches, the maintenance task), so a second process on the same data would
misbehave in subtle ways; it's refused at startup instead (README: "Scaling and limits").
"""
import contextlib
import fcntl
import os

from app.config import DATA_DIR

LOCK_FILE = DATA_DIR / "habeny.lock"
_fd: int | None = None


class AlreadyRunning(RuntimeError):
    pass


def acquire() -> None:
    """Take the data directory's lock for this process's lifetime."""
    global _fd
    if _fd is not None:
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fd = os.open(LOCK_FILE, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        pid = os.read(fd, 32).decode(errors="replace").strip() or "?"
        os.close(fd)
        raise AlreadyRunning(
            f"Another Habeny (pid {pid}) is already running with data directory {DATA_DIR}. Only one instance "
            f"can use a data directory: stop the other one (sudo systemctl stop habeny), or give this one its own "
            f"HABENY_DATA_DIR. Don't run uvicorn with several workers."
        ) from None
    os.ftruncate(fd, 0)
    os.write(fd, str(os.getpid()).encode())
    _fd = fd


def drop_inherited_lock() -> None:
    """In forked worker processes: close the inherited lock descriptor, so a worker that
    outlives the main process doesn't keep the data directory locked."""
    global _fd
    if _fd is not None:
        with contextlib.suppress(OSError):
            os.close(_fd)
        _fd = None


def running_pid() -> int | None:
    """The pid of the Habeny holding the lock, or None if no instance is running."""
    try:
        fd = os.open(LOCK_FILE, os.O_RDONLY)
    except FileNotFoundError:
        return None
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except BlockingIOError:
        try:
            return int(os.read(fd, 32).decode().strip() or 0) or -1
        except ValueError:
            return -1
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)
        return None
    finally:
        os.close(fd)
