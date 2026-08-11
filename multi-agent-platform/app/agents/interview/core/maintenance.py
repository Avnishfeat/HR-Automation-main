"""Periodic maintenance for interview records and local artifacts."""

import asyncio
from datetime import datetime, timezone
import logging
from threading import Lock
from typing import Any

from app.agents.interview.core.local_state import cleanup_expired_session_data
from app.agents.interview.database import cleanup_expired_interviews

logger = logging.getLogger(__name__)
_maintenance_lock = Lock()
_last_result: dict[str, Any] = {"last_run_at": None, "last_result": None}


async def run_local_retention_cleanup() -> dict[str, Any]:
    """Run conservative database and local-artifact retention cleanup."""
    result: dict[str, Any] = {}
    try:
        result["database"] = await cleanup_expired_interviews()
    except Exception:
        logger.exception("Database interview-retention cleanup failed")
        result["database"] = {"error": "cleanup_failed"}
    try:
        result["session_data"] = await asyncio.to_thread(cleanup_expired_session_data)
    except Exception:
        logger.exception("Local session-data retention cleanup failed")
        result["session_data"] = {"error": "cleanup_failed"}
    with _maintenance_lock:
        _last_result["last_run_at"] = datetime.now(timezone.utc).isoformat()
        _last_result["last_result"] = result
    return result


def get_maintenance_status() -> dict[str, Any]:
    with _maintenance_lock:
        return dict(_last_result)
