"""
Alerts: conditions someone should act on. Shown in the UI, exported to Prometheus
(habeny_alerts_active) and sent to notification channels when they start and clear.

- disk_low: free space for data or containers under HABENY_ALERT_DISK_PERCENT
- lxc_unavailable: container operations can't reach LXC (e.g. the helper is down)
- backup_failed: the last scheduled backup failed
- deploy_failed: the last deployment had failures (clears after one that fully succeeds)
- host_unreachable: another Habeny server managed from this console doesn't answer
- license: the license expires soon, has expired, or the trial is ending (see licensing.py)

Conditions are checked every minute by the maintenance task; deployment and backup
results set or clear their alerts as they happen.
"""
import logging
import threading
from dataclasses import asdict, dataclass, field
from typing import Any

from app.models import utc_now

logger = logging.getLogger(__name__)

LABELS = {
    "disk_low": "Low disk space",
    "lxc_unavailable": "LXC unavailable",
    "backup_failed": "Backup failed",
    "deploy_failed": "Deployment failed",
    "host_unreachable": "Host unreachable",
    "license": "License",
}


@dataclass
class Alert:
    name: str
    severity: str  # warning | critical
    message: str
    target: str | None = None
    since: str = field(default_factory=lambda: utc_now().isoformat())
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.name}:{self.target}" if self.target else self.name


class AlertManager:
    def __init__(self):
        self._active: dict[str, Alert] = {}
        self._lock = threading.Lock()

    def fire(self, name: str, severity: str, message: str, target: str | None = None,
             details: dict | None = None, link: str | None = None) -> None:
        alert = Alert(name, severity, message, target, details=details or {})
        with self._lock:
            previous = self._active.get(alert.key)
            if previous:
                alert.since = previous.since  # still the same episode
            self._active[alert.key] = alert
        if previous is None or previous.severity != severity:
            logger.warning(f"Alert: {message}", extra={"fields": {"alert": name, "target": target}})
            _notify("alert.firing", alert, link)

    def clear(self, name: str, target: str | None = None, message: str | None = None) -> None:
        key = f"{name}:{target}" if target else name
        with self._lock:
            alert = self._active.pop(key, None)
        if alert:
            logger.info(f"Alert cleared: {alert.message}", extra={"fields": {"alert": name, "target": target}})
            alert.message = message or f"{LABELS.get(name, name)} cleared"
            _notify("alert.resolved", alert, None)

    def active(self) -> list[dict[str, Any]]:
        with self._lock:
            alerts = list(self._active.values())
        return [{**asdict(a), "label": LABELS.get(a.name, a.name)} for a in
                sorted(alerts, key=lambda a: (a.severity != "critical", a.since))]

    def reset(self) -> None:
        """Tests."""
        with self._lock:
            self._active.clear()


manager = AlertManager()


def _notify(event: str, alert: Alert, link: str | None) -> None:
    from app.services import notify
    firing = event == "alert.firing"
    title = f"{LABELS.get(alert.name, alert.name)}{f' ({alert.target})' if alert.target else ''}"
    notify.emit(event, title if firing else f"Resolved: {title}", alert.message,
                level=("error" if alert.severity == "critical" else "warning") if firing else "success",
                fields={k: v for k, v in alert.details.items() if not isinstance(v, (dict, list))},
                link=link or "/monitoring")


# ── periodic checks ─────────────────────────────────────────────────────

def check() -> None:
    """Evaluate the conditions that aren't event-driven. Called every minute."""
    from app import config
    from app.services import telemetry

    threshold = config.get("HABENY_ALERT_DISK_PERCENT")
    for target, usage in telemetry.disk_usage().items():
        percent_free = usage["free"] * 100 / usage["total"] if usage["total"] else 100
        if threshold and percent_free < threshold:
            severity = "critical" if percent_free < threshold / 2 else "warning"
            manager.fire("disk_low", severity,
                         f"Only {percent_free:.1f}% free ({usage['free'] / 1e9:.1f} GB) on {usage['path']} "
                         f"({'containers' if target == 'containers' else 'Habeny data'})",
                         target=target, details={"path": usage["path"], "free_gb": round(usage["free"] / 1e9, 1),
                                                 "percent_free": round(percent_free, 1)})
        else:
            manager.clear("disk_low", target, f"Disk space for {target} is back above {threshold}%")

    try:
        from app.core.lxc_backend import has_lxc_access, lxc
        if not has_lxc_access():
            raise RuntimeError("no root and no helper")
        lxc.list_containers()
    except Exception as e:
        manager.fire("lxc_unavailable", "critical", f"Container operations can't reach LXC: {e}",
                     details={"error": str(e)[:300]})
    else:
        manager.clear("lxc_unavailable", message="LXC is reachable again")

    from app.services import hosts, licensing
    hosts.check_all()
    licensing.check_alert()


def deployment_finished(deployment_id: str, requested: int, successful: int, failed: int, error: str | None) -> None:
    if failed or error:
        manager.fire("deploy_failed", "critical" if not successful else "warning",
                     f"Deployment {deployment_id}: {failed} of {requested} containers failed"
                     + (f" ({error})" if error else ""),
                     details={"deployment_id": deployment_id, "requested": requested, "successful": successful,
                              "failed": failed}, link="/deploy")
    else:
        manager.clear("deploy_failed", message=f"Deployment {deployment_id} succeeded ({successful} containers)")


def backup_result(error: str | None) -> None:
    if error:
        manager.fire("backup_failed", "critical", f"The scheduled backup failed: {error}",
                     details={"error": error[:300]}, link="/account")
    else:
        manager.clear("backup_failed", message="Scheduled backups work again")
