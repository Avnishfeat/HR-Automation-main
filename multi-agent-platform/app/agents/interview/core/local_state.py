"""Small file-backed terminal status records for the single-worker deployment."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import logging
import shutil
from typing import Optional

from app.agents.interview.config.constants import StoragePaths

logger = logging.getLogger(__name__)


def _status_path(session_id: str) -> Path:
    return Path(StoragePaths.DATA_ROOT) / session_id / "terminal_status.json"


def save_terminal_status(session_id: str, status: str) -> None:
    path = _status_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(
            {
                "session_id": session_id,
                "status": status,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    os.replace(temporary_path, path)


def get_terminal_status(session_id: str) -> Optional[dict[str, str]]:
    try:
        value = json.loads(_status_path(session_id).read_text(encoding="utf-8"))
        if value.get("session_id") == session_id and isinstance(value.get("status"), str):
            return value
    except (OSError, ValueError, TypeError):
        return None
    return None


def cleanup_expired_session_data(retention_days: Optional[int] = None) -> dict[str, int]:
    """Delete completed session directories older than the configured retention period.

    A directory is eligible only when it contains a valid terminal-status file,
    so active interviews and unrelated data directories are never removed.
    """
    if retention_days is None:
        try:
            retention_days = max(0, int(os.getenv("INTERVIEW_SESSION_RETENTION_DAYS", "30")))
        except ValueError:
            retention_days = 30
            logger.warning("Invalid INTERVIEW_SESSION_RETENTION_DAYS; using 30 days")

    root = Path(StoragePaths.DATA_ROOT).resolve()
    summary = {"session_directories_deleted": 0, "skipped": 0}
    if not root.exists():
        return summary
    cutoff = datetime.now(timezone.utc).timestamp() - retention_days * 86_400

    for directory in root.iterdir():
        if not directory.is_dir() or directory.is_symlink():
            continue
        status_path = directory / "terminal_status.json"
        try:
            status = json.loads(status_path.read_text(encoding="utf-8"))
            completed_at = datetime.fromisoformat(status["completed_at"])
            completed_at = completed_at if completed_at.tzinfo else completed_at.replace(tzinfo=timezone.utc)
            if completed_at.timestamp() > cutoff:
                summary["skipped"] += 1
                continue
            # Resolve once more before deletion to prevent an unexpected path escape.
            resolved_directory = directory.resolve()
            if root not in resolved_directory.parents:
                summary["skipped"] += 1
                continue
            shutil.rmtree(resolved_directory)
            summary["session_directories_deleted"] += 1
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
            summary["skipped"] += 1
            if status_path.exists():
                logger.warning("Could not evaluate session retention for %s: %s", directory, error)
    return summary
