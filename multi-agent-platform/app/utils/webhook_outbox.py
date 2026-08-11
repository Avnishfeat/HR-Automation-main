"""Disk-backed webhook delivery for interview completion events."""

import asyncio
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
from threading import Lock
from typing import Any, Optional
from uuid import uuid4

import requests

from app.agents.interview.config.constants import StoragePaths

logger = logging.getLogger(__name__)

OUTBOX_DIR = Path(StoragePaths.DATA_ROOT) / "webhook_outbox"
MAX_ATTEMPTS = 4
RETRY_DELAYS_SECONDS = (30, 60, 120)
_outbox_lock = Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    temporary_path = path.with_suffix(".tmp")
    temporary_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(temporary_path, 0o600)
    os.replace(temporary_path, path)


def enqueue_webhook(
    webhook_url: str,
    payload: dict[str, Any],
    headers: Optional[dict[str, str]] = None,
) -> str:
    """Persist an event before it is delivered, returning its stable event ID."""
    event_id = str(uuid4())
    now = _now().isoformat()
    event = {
        "id": event_id,
        "url": webhook_url,
        "payload": payload,
        "headers": headers or {},
        "status": "pending",
        "attempts": 0,
        "created_at": now,
        "next_attempt_at": now,
        "last_error": None,
    }
    with _outbox_lock:
        _atomic_write(OUTBOX_DIR / f"{event_id}.json", event)
    logger.info("Queued webhook event %s", event_id)
    return event_id


def _load_event(path: Path) -> Optional[dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        logger.error("Could not read webhook outbox event %s: %s", path, error)
        return None


def _is_due(event: dict[str, Any], now: datetime) -> bool:
    if event.get("status") != "pending":
        return False
    try:
        return datetime.fromisoformat(event["next_attempt_at"]) <= now
    except (KeyError, TypeError, ValueError):
        return True


def _next_retry_delay(attempts: int) -> int:
    index = min(max(attempts - 1, 0), len(RETRY_DELAYS_SECONDS) - 1)
    return RETRY_DELAYS_SECONDS[index]


def deliver_due_webhooks(max_events: int = 5) -> dict[str, int]:
    """Deliver due events once without blocking the application's event loop."""
    summary = {"delivered": 0, "retried": 0, "failed": 0, "skipped": 0}
    now = _now()
    with _outbox_lock:
        paths = sorted(OUTBOX_DIR.glob("*.json")) if OUTBOX_DIR.exists() else []
        due_events = []
        for path in paths:
            event = _load_event(path)
            if not event:
                summary["skipped"] += 1
                continue
            if not _is_due(event, now):
                summary["skipped"] += 1
                continue
            due_events.append((path, event))

        for path, event in due_events[:max_events]:
            event["attempts"] = int(event.get("attempts", 0)) + 1
            try:
                response = requests.post(
                    event["url"],
                    json=event["payload"],
                    headers=event.get("headers") or None,
                    timeout=10,
                )
                if 200 <= response.status_code < 300:
                    event["status"] = "delivered"
                    event["delivered_at"] = _now().isoformat()
                    event["last_error"] = None
                    summary["delivered"] += 1
                else:
                    raise requests.HTTPError(f"Webhook returned HTTP {response.status_code}")
            except requests.RequestException as error:
                event["last_error"] = str(error)[:2_000]
                if event["attempts"] >= MAX_ATTEMPTS:
                    event["status"] = "failed"
                    event["failed_at"] = _now().isoformat()
                    summary["failed"] += 1
                    logger.error("Webhook event %s moved to failed state: %s", event.get("id"), error)
                else:
                    delay = _next_retry_delay(event["attempts"])
                    event["next_attempt_at"] = (_now() + timedelta(seconds=delay)).isoformat()
                    summary["retried"] += 1
                    logger.warning("Webhook event %s will retry in %ss: %s", event.get("id"), delay, error)
            _atomic_write(path, event)
    return summary


async def deliver_due_webhooks_async(max_events: int = 5) -> dict[str, int]:
    return await asyncio.to_thread(deliver_due_webhooks, max_events)


def get_outbox_status() -> dict[str, int]:
    counts = {"pending": 0, "delivered": 0, "failed": 0}
    with _outbox_lock:
        paths = OUTBOX_DIR.glob("*.json") if OUTBOX_DIR.exists() else []
        for path in paths:
            event = _load_event(path)
            if event and event.get("status") in counts:
                counts[event["status"]] += 1
    return counts


def _retention_days(variable_name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(variable_name, str(default))))
    except ValueError:
        logger.warning("Invalid %s; using %s days", variable_name, default)
        return default


def _event_age_reference(event: dict[str, Any]) -> Optional[datetime]:
    for key in ("delivered_at", "failed_at", "created_at"):
        value = event.get(key)
        if not isinstance(value, str):
            continue
        try:
            timestamp = datetime.fromisoformat(value)
            return timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def cleanup_outbox(
    delivered_retention_days: Optional[int] = None,
    failed_retention_days: Optional[int] = None,
) -> dict[str, int]:
    """Remove only expired terminal outbox events; pending events are never deleted."""
    delivered_days = (
        _retention_days("WEBHOOK_OUTBOX_DELIVERED_RETENTION_DAYS", 7)
        if delivered_retention_days is None else max(0, delivered_retention_days)
    )
    failed_days = (
        _retention_days("WEBHOOK_OUTBOX_FAILED_RETENTION_DAYS", 90)
        if failed_retention_days is None else max(0, failed_retention_days)
    )
    summary = {"delivered_deleted": 0, "failed_deleted": 0, "skipped": 0}
    now = _now()

    with _outbox_lock:
        paths = OUTBOX_DIR.glob("*.json") if OUTBOX_DIR.exists() else []
        for path in paths:
            event = _load_event(path)
            if not event:
                summary["skipped"] += 1
                continue
            status = event.get("status")
            retention_days = delivered_days if status == "delivered" else failed_days if status == "failed" else None
            reference_time = _event_age_reference(event)
            if retention_days is None or reference_time is None or now - reference_time < timedelta(days=retention_days):
                summary["skipped"] += 1
                continue
            try:
                path.unlink()
                summary[f"{status}_deleted"] += 1
            except OSError as error:
                summary["skipped"] += 1
                logger.warning("Could not remove expired outbox event %s: %s", path, error)
    return summary
