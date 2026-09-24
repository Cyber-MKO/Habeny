"""
Graceful shutdown. On SIGTERM/SIGINT (systemctl stop/restart, Ctrl+C):

1. Requests that would change something get 503, so no new deployment starts.
2. Deployments in progress finish the containers they're working on; containers still
   queued are cancelled and reported as interrupted.
3. After HABENY_SHUTDOWN_TIMEOUT seconds, whatever is still running is abandoned and
   marked interrupted, and the server exits.

At the next start, containers left mid-deployment by a crash or power loss are marked
interrupted too (see recover_interrupted_deployments).
"""
import logging
import signal
import threading
import time

from app.config import SHUTDOWN_TIMEOUT

logger = logging.getLogger(__name__)

_stopping = threading.Event()
_deadline: float | None = None
_lock = threading.Lock()

INTERRUPTED = "interrupted"


_hooks: list = []


def on_shutdown(callback) -> None:
    """Run `callback()` as soon as a stop begins: long-running work that isn't a deployment
    (simulations, log schedules) winds down instead of holding the stop up."""
    _hooks.append(callback)


def begin_shutdown() -> None:
    global _deadline
    with _lock:
        if _stopping.is_set():
            return
        _deadline = time.monotonic() + SHUTDOWN_TIMEOUT
        _stopping.set()
    logger.warning(f"Shutting down: refusing new changes, letting running deployments finish "
                   f"(up to {SHUTDOWN_TIMEOUT}s)")
    for hook in _hooks:
        try:
            hook()
        except Exception:
            logger.exception(f"Shutdown hook {getattr(hook, '__name__', hook)} failed")


def shutting_down() -> bool:
    return _stopping.is_set()


def time_left() -> float:
    """Seconds until running work is abandoned (inf while not shutting down)."""
    if _deadline is None:
        return float("inf")
    return max(0.0, _deadline - time.monotonic())


def ignore_stop_signals() -> None:
    """ProcessPool initializer: workers leave SIGINT/SIGTERM to the main process, which
    lets them finish (Ctrl+C in a terminal reaches the whole process group). They also
    let go of the inherited instance lock (see app/services/instance.py)."""
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    from app.services.instance import drop_inherited_lock
    drop_inherited_lock()


def recover_interrupted_deployments() -> int:
    """Containers still marked "starting" when the server starts were being deployed when
    it stopped unexpectedly; say so instead of showing them as starting forever."""
    from app.config import DB_PATH
    from app.db import mark_agents_interrupted
    count = mark_agents_interrupted(DB_PATH, from_status="starting", to_status=INTERRUPTED)
    if count:
        logger.warning(f"{count} container(s) were mid-deployment when Habeny last stopped; marked "
                       f"'{INTERRUPTED}' (delete and redeploy them)")
    return count


def _reset_for_tests() -> None:
    global _deadline
    _stopping.clear()
    _deadline = None
