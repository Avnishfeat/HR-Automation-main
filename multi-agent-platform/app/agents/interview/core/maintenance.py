"""Periodic maintenance for local interview artifacts."""

from datetime import datetime, timezone
from threading import Lock
from typing import Any

from app.agents.interview.core.local_state import cleanup_expired_session_data
from app.utils.webhook_outbox import cleanup_outbox

_maintenance_lock = Lock()
_last_result: dict[str, Any] = {"last_run_at": None, "last_result": None}


def run_local_retention_cleanup() -> dict[str, Any]:
    """Run conservative retention cleanup and retain a health-report snapshot."""
    result = {
        "webhook_outbox": cleanup_outbox(),
        "session_data": cleanup_expired_session_data(),
    }
    with _maintenance_lock:
        _last_result["last_run_at"] = datetime.now(timezone.utc).isoformat()
        _last_result["last_result"] = result
    return result


def get_maintenance_status() -> dict[str, Any]:
    with _maintenance_lock:
        return dict(_last_result)
