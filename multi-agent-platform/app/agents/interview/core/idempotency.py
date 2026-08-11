"""File-backed idempotency for interview-start requests in one-worker deployments."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
from threading import Lock
from typing import Iterator, Optional

try:  # The production VM is Linux; the fallback keeps local development portable.
    import fcntl
except ImportError:  # pragma: no cover - Windows does not provide fcntl.
    fcntl = None

from app.agents.interview.config.constants import StoragePaths

logger = logging.getLogger(__name__)

IDEMPOTENCY_STATE_PATH = Path(StoragePaths.DATA_ROOT) / "interview_idempotency.json"
IDEMPOTENCY_LOCK_PATH = Path(StoragePaths.DATA_ROOT) / "interview_idempotency.lock"
MAX_IDEMPOTENCY_KEY_LENGTH = 256
RESERVATION_TIMEOUT_SECONDS = 300
DEFAULT_RETENTION_DAYS = 30

_thread_lock = Lock()


def normalize_idempotency_key(value: Optional[str]) -> Optional[str]:
    """Validate the optional request header without persisting its raw value."""
    if value is None:
        return None
    key = value.strip()
    if not key:
        raise ValueError("X-Idempotency-Key must not be blank")
    if len(key) > MAX_IDEMPOTENCY_KEY_LENGTH:
        raise ValueError(
            f"X-Idempotency-Key must be at most {MAX_IDEMPOTENCY_KEY_LENGTH} characters"
        )
    if any(not character.isprintable() for character in key):
        raise ValueError("X-Idempotency-Key must contain printable characters only")
    return key


def lookup_idempotency_key(key: str) -> tuple[str, Optional[dict[str, str]]]:
    """Return ``replay``, ``in_progress``, or ``new`` for a supplied key."""
    key_hash = _hash_key(key)
    with _state_lock():
        state = _load_state()
        record = state.get(key_hash)
        if not record:
            return "new", None
        if _is_expired_reservation(record):
            del state[key_hash]
            _save_state(state)
            return "new", None
        if record.get("status") == "accepted":
            return "replay", record
        return "in_progress", record


def reserve_idempotency_key(key: str, session_id: str) -> tuple[str, dict[str, str]]:
    """Atomically reserve a new key or return its prior request outcome."""
    key_hash = _hash_key(key)
    with _state_lock():
        state = _load_state()
        existing = state.get(key_hash)
        if existing and not _is_expired_reservation(existing):
            if existing.get("status") == "accepted":
                return "replay", existing
            return "in_progress", existing
        if existing:
            del state[key_hash]

        record = {
            "key_hash": key_hash,
            "session_id": session_id,
            "status": "reserved",
            "created_at": _now(),
        }
        state[key_hash] = record
        _save_state(state)
        return "reserved", record


def accept_idempotency_key(key: str, session_id: str) -> None:
    """Mark a successfully scheduled interview as safe to replay."""
    key_hash = _hash_key(key)
    with _state_lock():
        state = _load_state()
        record = state.get(key_hash)
        if not record or record.get("session_id") != session_id:
            raise RuntimeError("Idempotency reservation was not found for the scheduled session")
        record["status"] = "accepted"
        record["accepted_at"] = _now()
        state[key_hash] = record
        _save_state(state)


def release_idempotency_key(key: Optional[str], session_id: str) -> None:
    """Release only this request's reservation after scheduling fails."""
    if not key:
        return
    key_hash = _hash_key(key)
    with _state_lock():
        state = _load_state()
        record = state.get(key_hash)
        if record and record.get("session_id") == session_id and record.get("status") == "reserved":
            del state[key_hash]
            _save_state(state)


def cleanup_expired_idempotency_keys(retention_days: Optional[int] = None) -> dict[str, int]:
    """Remove old replay records and abandoned reservations."""
    if retention_days is None:
        try:
            retention_days = max(0, int(os.getenv("IDEMPOTENCY_KEY_RETENTION_DAYS", str(DEFAULT_RETENTION_DAYS))))
        except ValueError:
            retention_days = DEFAULT_RETENTION_DAYS
            logger.warning("Invalid IDEMPOTENCY_KEY_RETENTION_DAYS; using %s days", retention_days)

    cutoff = datetime.now(timezone.utc).timestamp() - retention_days * 86_400
    summary = {"accepted_deleted": 0, "reservations_deleted": 0, "skipped": 0}
    with _state_lock():
        state = _load_state()
        for key_hash, record in list(state.items()):
            if _is_expired_reservation(record):
                del state[key_hash]
                summary["reservations_deleted"] += 1
                continue
            timestamp = _parse_timestamp(record.get("accepted_at") or record.get("created_at"))
            if timestamp is None:
                summary["skipped"] += 1
                continue
            if timestamp <= cutoff:
                del state[key_hash]
                summary["accepted_deleted"] += 1
        _save_state(state)
    return summary


def _hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _is_expired_reservation(record: dict[str, str]) -> bool:
    if record.get("status") == "accepted":
        return False
    created_at = _parse_timestamp(record.get("created_at"))
    return created_at is None or datetime.now(timezone.utc).timestamp() - created_at >= RESERVATION_TIMEOUT_SECONDS


def _parse_timestamp(value: object) -> Optional[float]:
    if not isinstance(value, str):
        return None
    try:
        timestamp = datetime.fromisoformat(value)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return timestamp.timestamp()
    except ValueError:
        return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _state_lock() -> Iterator[None]:
    """Serialize state changes across threads and Linux worker processes."""
    with _thread_lock:
        IDEMPOTENCY_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        with IDEMPOTENCY_LOCK_PATH.open("a+") as lock_file:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _load_state() -> dict[str, dict[str, str]]:
    try:
        value = json.loads(IDEMPOTENCY_STATE_PATH.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Idempotency state is not a JSON object")
        return {
            key: record
            for key, record in value.items()
            if isinstance(key, str) and isinstance(record, dict)
        }
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, json.JSONDecodeError) as error:
        logger.error("Could not read idempotency state; treating it as empty: %s", error)
        return {}


def _save_state(state: dict[str, dict[str, str]]) -> None:
    IDEMPOTENCY_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = IDEMPOTENCY_STATE_PATH.with_suffix(".tmp")
    temporary_path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    os.replace(temporary_path, IDEMPOTENCY_STATE_PATH)
