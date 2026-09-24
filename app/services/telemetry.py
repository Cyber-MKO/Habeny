"""
Prometheus metrics (GET /metrics, text exposition format 0.0.4).

Counters and the request-duration histogram live in this process (they restart from
zero with Habeny, which Prometheus handles); gauges are read when scraped. Scrape with
an API token (viewer role is enough):

    scrape_configs:
      - job_name: habeny
        scheme: https
        authorization: {credentials_file: /etc/prometheus/habeny.token}
        static_configs: [{targets: ["habeny.example.com:9000"]}]
"""
import os
import shutil
import threading
import time
from collections.abc import Iterable

_lock = threading.Lock()
LXC_PATH = "/var/lib/lxc"  # where LXC keeps container root filesystems
PROCESS_STARTED = time.time()


def _labels(labels: dict[str, str]) -> str:
    if not labels:
        return ""
    body = ",".join(f'{k}="{_escape(str(v))}"' for k, v in sorted(labels.items()))
    return "{" + body + "}"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _num(value: float) -> str:
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return repr(float(value))


class Counter:
    def __init__(self, name: str, help_text: str):
        self.name, self.help = name, help_text
        self._values: dict[tuple, float] = {}

    def inc(self, amount: float = 1, **labels: str) -> None:
        key = tuple(sorted(labels.items()))
        with _lock:
            self._values[key] = self._values.get(key, 0) + amount

    def value(self, **labels: str) -> float:
        return self._values.get(tuple(sorted(labels.items())), 0)

    def render(self) -> Iterable[str]:
        yield f"# HELP {self.name} {self.help}"
        yield f"# TYPE {self.name} counter"
        with _lock:
            items = list(self._values.items())
        for key, value in items:
            yield f"{self.name}{_labels(dict(key))} {_num(value)}"


class Histogram:
    BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30)

    def __init__(self, name: str, help_text: str):
        self.name, self.help = name, help_text
        self._series: dict[tuple, list] = {}  # key -> [bucket counts..., sum, count]

    def observe(self, value: float, **labels: str) -> None:
        key = tuple(sorted(labels.items()))
        with _lock:
            series = self._series.setdefault(key, [0] * len(self.BUCKETS) + [0.0, 0])
            for i, bound in enumerate(self.BUCKETS):
                if value <= bound:
                    series[i] += 1
            series[-2] += value
            series[-1] += 1

    def render(self) -> Iterable[str]:
        yield f"# HELP {self.name} {self.help}"
        yield f"# TYPE {self.name} histogram"
        with _lock:
            items = [(k, list(v)) for k, v in self._series.items()]
        for key, series in items:
            labels = dict(key)
            for bound, count in zip(self.BUCKETS, series, strict=False):
                yield f"{self.name}_bucket{_labels({**labels, 'le': _num(bound)})} {count}"
            yield f"{self.name}_bucket{_labels({**labels, 'le': '+Inf'})} {series[-1]}"
            yield f"{self.name}_sum{_labels(labels)} {repr(round(series[-2], 6))}"
            yield f"{self.name}_count{_labels(labels)} {series[-1]}"


HTTP_REQUESTS = Counter("habeny_http_requests_total", "HTTP requests handled, by method and status class")
HTTP_DURATION = Histogram("habeny_http_request_duration_seconds", "Time to answer HTTP requests")
DEPLOYMENTS = Counter("habeny_deployments_total", "Finished deployments by result (completed, partial, failed)")
CONTAINERS_DEPLOYED = Counter("habeny_containers_deployed_total", "Containers deployed, by result (success, failure)")
SIMULATIONS = Counter("habeny_simulations_finished_total", "Finished simulations by status")
BENCHMARKS = Counter("habeny_benchmarks_finished_total", "Finished benchmarks by status")
NOTIFICATIONS = Counter("habeny_notifications_total", "Notifications by channel type and result (sent, failed)")
COUNTERS = (HTTP_REQUESTS, DEPLOYMENTS, CONTAINERS_DEPLOYED, SIMULATIONS, BENCHMARKS, NOTIFICATIONS)


def observe_request(method: str, status: int | None, seconds: float) -> None:
    status_class = f"{str(status)[0]}xx" if status else "none"
    HTTP_REQUESTS.inc(method=method, code=status_class)
    HTTP_DURATION.observe(seconds, method=method)


def _gauge(name: str, help_text: str, samples: Iterable[tuple[dict, float]]) -> list[str]:
    lines = [f"# HELP {name} {help_text}", f"# TYPE {name} gauge"]
    lines += [f"{name}{_labels(labels)} {_num(value)}" for labels, value in samples]
    return lines


def disk_usage() -> dict[str, dict[str, int]]:
    """Free and total bytes where Habeny keeps data and where LXC keeps containers."""
    from app.config import DATA_DIR
    paths = {"data": DATA_DIR, "containers": LXC_PATH}
    usage = {}
    for target, path in paths.items():
        try:
            u = shutil.disk_usage(path)
        except OSError:
            continue
        usage[target] = {"path": str(path), "free": u.free, "total": u.total}
    return usage


def _safe(fn, default):
    try:
        return fn()
    except Exception:
        return default


def render() -> str:
    """The whole exposition. Blocking (reads containers and the database): run it in a thread."""
    from app.config import DB_PATH
    from app.services import alerts
    from app.services.agent_info import container_state_summary
    from app.services.backup import list_backups
    from app.state import deployment_progress, simulations_db
    from app.version import __version__

    lines: list[str] = []
    lines += _gauge("habeny_info", "Habeny version", [({"version": __version__}, 1)])
    lines += _gauge("habeny_uptime_seconds", "Seconds since Habeny started", [({}, round(time.time() - PROCESS_STARTED))])

    scan = _safe(container_state_summary, None)
    lines += _gauge("habeny_lxc_up", "Whether LXC answered (1) or not (0)", [({}, 1 if scan else 0)])
    if scan:
        lines += _gauge("habeny_containers", "Containers by state",
                        [({"state": state.lower()}, count) for state, count in scan["by_state"].items()])
    running_deploys = sum(1 for d in list(deployment_progress.values()) if d.get("status") == "running")
    lines += _gauge("habeny_deployments_running", "Deployments in progress", [({}, running_deploys)])
    running_sims = sum(1 for s in list(simulations_db.values()) if s.get("status") == "running")
    lines += _gauge("habeny_simulations_running", "Simulations in progress", [({}, running_sims)])

    usage = disk_usage()
    lines += _gauge("habeny_disk_free_bytes", "Free disk space",
                    [({"target": t, "path": u["path"]}, u["free"]) for t, u in usage.items()])
    lines += _gauge("habeny_disk_size_bytes", "Disk size",
                    [({"target": t, "path": u["path"]}, u["total"]) for t, u in usage.items()])
    db_size = sum(_safe(lambda p=p: os.path.getsize(p), 0) for p in (DB_PATH, f"{DB_PATH}-wal"))
    lines += _gauge("habeny_database_size_bytes", "Database size (with its write-ahead log)", [({}, db_size)])

    backups = _safe(list_backups, [])
    lines += _gauge("habeny_backups", "Full backups kept", [({}, len(backups))])
    if backups:
        from datetime import datetime
        newest = datetime.fromisoformat(backups[0]["created_at"]).timestamp()
        lines += _gauge("habeny_backup_last_timestamp_seconds", "When the newest full backup was taken",
                        [({}, int(newest))])

    active = alerts.manager.active()
    lines += _gauge("habeny_alerts_active", "Active alerts (1 per alert)",
                    [({"alert": a["name"], "target": a.get("target") or "", "severity": a["severity"]}, 1)
                     for a in active])

    counts = _safe(_account_counts, {})
    if counts:
        lines += _gauge("habeny_users", "User accounts", [({}, counts["users"])])
        lines += _gauge("habeny_sessions_active", "Signed-in browser sessions", [({}, counts["sessions"])])
        lines += _gauge("habeny_api_tokens", "API tokens", [({}, counts["tokens"])])

    load = _safe(os.getloadavg, None)
    if load:
        lines += _gauge("habeny_host_load", "Host load average",
                        [({"period": p}, round(v, 2)) for p, v in zip(("1m", "5m", "15m"), load, strict=True)])
    mem = _safe(_meminfo, None)
    if mem:
        lines += _gauge("habeny_host_memory_bytes", "Host memory",
                        [({"kind": "total"}, mem["MemTotal"]), ({"kind": "available"}, mem["MemAvailable"])])

    for metric in (*COUNTERS, HTTP_DURATION):
        lines += list(metric.render())
    return "\n".join(lines) + "\n"


def _account_counts() -> dict[str, int]:
    import sqlite3

    from app.config import DB_PATH
    from app.models import utc_now
    conn = sqlite3.connect(DB_PATH, timeout=5)
    try:
        now = utc_now().isoformat()
        return {
            "users": conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
            "sessions": conn.execute("SELECT COUNT(*) FROM sessions WHERE expires_at > ?", (now,)).fetchone()[0],
            "tokens": conn.execute("SELECT COUNT(*) FROM api_tokens WHERE expires_at IS NULL OR expires_at > ?",
                                   (now,)).fetchone()[0],
        }
    finally:
        conn.close()


def _meminfo() -> dict[str, int]:
    values = {}
    with open("/proc/meminfo") as f:
        for line in f:
            key, _, rest = line.partition(":")
            if key in ("MemTotal", "MemAvailable"):
                values[key] = int(rest.split()[0]) * 1024
    return values
