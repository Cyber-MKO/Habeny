"""
Activity logging: what happened, who did it, from where. Stored in the audit trail
(app/services/audit.py): searchable, exportable and tamper-evident.
"""
from typing import Any

from app.services import audit


def log_activity(action: str, details: dict[str, Any], status: str = "success", user: str | None = None):
    """Record an action. The user, API token, client IP and request ID come from the
    current request; pass `user` for actions outside one (e.g. the CLI)."""
    audit.record(action, details, status, user=user)
