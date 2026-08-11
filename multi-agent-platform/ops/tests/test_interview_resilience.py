"""Focused regression checks for operational interview hardening."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.interview.core import local_state
from app.agents.interview.infrastructure.browser import meet_controller
from app.utils import webhook_outbox


def test_outbox_cleanup_keeps_pending_and_removes_expired_terminal_events(tmp_path, monkeypatch):
    monkeypatch.setattr(webhook_outbox, "OUTBOX_DIR", tmp_path)
    old_time = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    webhook_outbox._atomic_write(tmp_path / "delivered.json", {
        "id": "delivered", "status": "delivered", "delivered_at": old_time,
    })
    webhook_outbox._atomic_write(tmp_path / "pending.json", {
        "id": "pending", "status": "pending", "created_at": old_time,
    })

    result = webhook_outbox.cleanup_outbox(delivered_retention_days=7, failed_retention_days=90)

    assert result["delivered_deleted"] == 1
    assert not (tmp_path / "delivered.json").exists()
    assert (tmp_path / "pending.json").exists()


def test_session_retention_removes_only_expired_terminal_session(tmp_path, monkeypatch):
    monkeypatch.setattr(local_state.StoragePaths, "DATA_ROOT", str(tmp_path))
    old_session = tmp_path / "old-session"
    old_session.mkdir()
    (old_session / "terminal_status.json").write_text(
        '{"session_id":"old-session","status":"completed","completed_at":"2020-01-01T00:00:00+00:00"}',
        encoding="utf-8",
    )
    active_session = tmp_path / "active-session"
    active_session.mkdir()
    (active_session / "transcript.txt").write_text("keep", encoding="utf-8")

    result = local_state.cleanup_expired_session_data(retention_days=30)

    assert result["session_directories_deleted"] == 1
    assert not old_session.exists()
    assert active_session.exists()


@pytest.mark.asyncio
async def test_browser_refuses_existing_chrome_profile_lock(tmp_path, monkeypatch):
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "SingletonLock").write_text("locked", encoding="utf-8")
    controller = meet_controller.MeetController(user_data_dir=str(profile), use_vb_audio=False)
    controller.cleanup = AsyncMock()
    playwright = MagicMock()
    playwright.start = AsyncMock(return_value=MagicMock())
    monkeypatch.setattr(meet_controller, "async_playwright", lambda: playwright)

    assert await controller.setup_driver() is False
    controller.cleanup.assert_awaited_once()
    playwright.start.return_value.chromium.launch_persistent_context.assert_not_called()
