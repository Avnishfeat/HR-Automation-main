"""PostgreSQL integration coverage for the Interview Agent persistence flow.

Run only with TEST_DATABASE_URL pointing to a disposable database whose name
contains ``test``. The fixture recreates its schema and must never target the
production interview database.
"""

from __future__ import annotations

import json
import os
import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.agents.interview.api.interview import get_interview_analysis
from app.agents.interview.core import background
from app.agents.interview.core.task_registry import (
    create_interview_task,
    mark_interview_tasks_shutting_down,
)
from app.agents.interview.database import (
    Base,
    Interview,
    InterviewEvent,
    IdempotencyKey,
    close_database,
    cleanup_expired_interviews,
    complete_interview,
    create_or_get_interview,
    database_session,
    get_interview_by_buss_id,
    initialize_database,
    mark_orphaned_interviews,
    update_interview_status,
)
from app.core.config import settings


def _test_database_url() -> str:
    value = os.getenv("TEST_DATABASE_URL")
    if not value:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL integration tests")

    database_name = make_url(value).database or ""
    if "test" not in database_name.lower():
        raise RuntimeError(
            "TEST_DATABASE_URL must target a separate database with 'test' in its name"
        )
    return value


@pytest.fixture
async def postgres_database():
    """Initialize a disposable schema in the current test's event loop."""
    test_url = _test_database_url()
    original_url = settings.DATABASE_URL
    settings.DATABASE_URL = test_url
    await close_database()

    schema_engine = create_async_engine(test_url)
    try:
        async with schema_engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
            await connection.run_sync(Base.metadata.create_all)
        await initialize_database()
        yield
    finally:
        await close_database()
        async with schema_engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await schema_engine.dispose()
        settings.DATABASE_URL = original_url


async def _create_interview(*, buss_id: str | None = None, idempotency_key: str | None = None):
    return await create_or_get_interview(
        session_id=str(uuid4()),
        buss_id=buss_id or f"BUSS-{uuid4()}",
        candidate_email="candidate@example.com",
        job_role="Backend Engineer",
        job_description="Build dependable APIs.",
        idempotency_key=idempotency_key,
    )


@pytest.mark.asyncio
async def test_start_persists_unique_buss_id_and_idempotent_retry(postgres_database):
    first, created = await _create_interview(
        buss_id="BUSS-UNIQUE-1", idempotency_key="appointment-unique-1"
    )
    assert created is True
    assert first.status == "pending"

    same_buss_id, created = await _create_interview(
        buss_id="BUSS-UNIQUE-1", idempotency_key="appointment-other-key"
    )
    assert created is False
    assert same_buss_id.session_id == first.session_id

    replay, created = await _create_interview(
        buss_id="BUSS-RETRY-1", idempotency_key="appointment-unique-1"
    )
    assert created is False
    assert replay.session_id == first.session_id


@pytest.mark.asyncio
async def test_pending_analysis_returns_202_with_polling_interval(postgres_database):
    interview, _ = await _create_interview(buss_id="BUSS-PENDING-1")

    response = await get_interview_analysis(interview.buss_id)
    assert isinstance(response, JSONResponse)
    assert response.status_code == 202
    payload = json.loads(response.body)
    assert payload == {
        "buss_id": "BUSS-PENDING-1",
        "session_id": interview.session_id,
        "status": "pending",
        "terminal_reason": None,
        "analysis": None,
        "agent_errors": [],
        "completed_at": None,
        "retry_after_seconds": 15,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "analysis"),
    [
        ("completed", {"recommendation": "hire", "transcript": ["answer"]}),
        ("error_candidate_no_show", None),
        ("error_analysis_failed", None),
    ],
)
async def test_terminal_analysis_returns_status_and_agent_errors(postgres_database, status, analysis):
    interview, _ = await _create_interview()
    errors = [
        {
            "timestamp": "2026-08-11T00:00:00+00:00",
            "component": "analysis",
            "type": "AnalysisError",
            "message": "Analysis provider did not respond",
        }
    ]
    await complete_interview(interview.session_id, status, analysis, errors)

    payload = await get_interview_analysis(interview.buss_id)
    assert isinstance(payload, dict)
    assert payload["status"] == status
    assert payload["terminal_reason"] == (None if status == "completed" else status)
    assert payload["analysis"] == analysis
    assert payload["agent_errors"] == errors
    assert payload["completed_at"] is not None


@pytest.mark.asyncio
async def test_restart_marks_only_active_interviews_interrupted(postgres_database):
    active, _ = await _create_interview(buss_id="BUSS-ACTIVE-1")
    await update_interview_status(active.session_id, "joining")

    completed, _ = await _create_interview(buss_id="BUSS-COMPLETE-1")
    await complete_interview(completed.session_id, "completed", {"result": "done"}, [])

    assert await mark_orphaned_interviews() == 1
    active_after_restart = await get_interview_by_buss_id(active.buss_id)
    completed_after_restart = await get_interview_by_buss_id(completed.buss_id)
    assert active_after_restart is not None
    assert active_after_restart.status == "interrupted"
    assert active_after_restart.terminal_reason == "backend_restarted"
    assert completed_after_restart is not None
    assert completed_after_restart.status == "completed"

    async with database_session() as session:
        event = await session.scalar(
            select(InterviewEvent)
            .where(InterviewEvent.session_id == active.session_id)
            .order_by(InterviewEvent.id.desc())
        )
    assert event is not None
    assert event.event_type == "interrupted"
    assert event.details == {"reason": "backend_restarted"}

    payload = await get_interview_analysis(active.buss_id)
    assert payload["status"] == "interrupted"
    assert payload["terminal_reason"] == "backend_restarted"


@pytest.mark.asyncio
async def test_graceful_shutdown_persists_backend_shutdown_reason(postgres_database, monkeypatch):
    interview, _ = await _create_interview(buss_id="BUSS-GRACEFUL-SHUTDOWN")
    candidate_wait = asyncio.Event()

    async def wait_for_candidate(_session_id: str) -> None:
        await candidate_wait.wait()

    meet_session_manager = SimpleNamespace(
        start_bot_session=AsyncMock(return_value=True),
        wait_for_candidate=AsyncMock(side_effect=wait_for_candidate),
        end_session=AsyncMock(),
    )
    interview_service = SimpleNamespace(
        get_candidate_name=MagicMock(return_value="Test Candidate"),
        end_interview_session=MagicMock(),
        cleanup_session_state=MagicMock(),
    )
    services = SimpleNamespace(
        meet_session_mgr=meet_session_manager,
        meet_orchestrator=None,
        combined_analyzer=None,
        interview_service=interview_service,
    )
    monkeypatch.setattr(background, "get_services", lambda: services)
    monkeypatch.setattr(background, "get_concurrency_limiter", lambda: None)
    monkeypatch.setattr(background, "save_terminal_status", MagicMock())

    task = asyncio.create_task(
        background.start_and_conduct_interview_task(
            session_id=interview.session_id,
            meet_link="https://meet.google.com/test-interview",
            candidate_email=interview.candidate_email,
            buss_id=interview.buss_id,
        )
    )
    for _ in range(50):
        current = await get_interview_by_buss_id(interview.buss_id)
        if current and current.status == "joining":
            break
        await asyncio.sleep(0)
    else:
        pytest.fail("Interview task did not reach joining state")

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    interrupted = await get_interview_by_buss_id(interview.buss_id)
    assert interrupted is not None
    assert interrupted.status == "interrupted"
    assert interrupted.terminal_reason == "backend_shutdown"

    async with database_session() as session:
        event = await session.scalar(
            select(InterviewEvent)
            .where(InterviewEvent.session_id == interview.session_id)
            .order_by(InterviewEvent.id.desc())
        )
    assert event is not None
    assert event.event_type == "interrupted"
    assert event.details["reason"] == "backend_shutdown"

    payload = await get_interview_analysis(interview.buss_id)
    assert payload["status"] == "interrupted"
    assert payload["terminal_reason"] == "backend_shutdown"


@pytest.mark.asyncio
async def test_shutdown_stop_signal_is_not_reported_as_candidate_no_show(postgres_database, monkeypatch):
    interview, _ = await _create_interview(buss_id="BUSS-SHUTDOWN-STOP-SIGNAL")
    candidate_wait = asyncio.Event()

    async def wait_for_candidate(_session_id: str) -> bool:
        await candidate_wait.wait()
        return False

    meet_session_manager = SimpleNamespace(
        start_bot_session=AsyncMock(return_value=True),
        wait_for_candidate=AsyncMock(side_effect=wait_for_candidate),
        end_session=AsyncMock(),
    )
    interview_service = SimpleNamespace(
        get_candidate_name=MagicMock(return_value="Test Candidate"),
        end_interview_session=MagicMock(),
        cleanup_session_state=MagicMock(),
    )
    services = SimpleNamespace(
        meet_session_mgr=meet_session_manager,
        meet_orchestrator=None,
        combined_analyzer=None,
        interview_service=interview_service,
    )
    monkeypatch.setattr(background, "get_services", lambda: services)
    monkeypatch.setattr(background, "get_concurrency_limiter", lambda: None)
    monkeypatch.setattr(background, "save_terminal_status", MagicMock())

    task = create_interview_task(
        interview.session_id,
        background.start_and_conduct_interview_task(
            session_id=interview.session_id,
            meet_link="https://meet.google.com/test-interview",
            candidate_email=interview.candidate_email,
            buss_id=interview.buss_id,
        ),
    )
    for _ in range(50):
        current = await get_interview_by_buss_id(interview.buss_id)
        if current and current.status == "joining":
            break
        await asyncio.sleep(0)
    else:
        pytest.fail("Interview task did not reach joining state")

    mark_interview_tasks_shutting_down()
    candidate_wait.set()
    await task

    interrupted = await get_interview_by_buss_id(interview.buss_id)
    assert interrupted is not None
    assert interrupted.status == "interrupted"
    assert interrupted.terminal_reason == "backend_shutdown"


@pytest.mark.asyncio
async def test_retention_removes_only_old_terminal_interviews(postgres_database):
    old_terminal, _ = await _create_interview(buss_id="BUSS-OLD-TERMINAL")
    fresh_terminal, _ = await _create_interview(buss_id="BUSS-FRESH-TERMINAL")
    old_active, _ = await _create_interview(buss_id="BUSS-OLD-ACTIVE")

    await complete_interview(old_terminal.session_id, "completed", {"result": "old"}, [])
    await complete_interview(fresh_terminal.session_id, "completed", {"result": "fresh"}, [])
    await update_interview_status(old_active.session_id, "joining")

    async with database_session() as session:
        async with session.begin():
            old_row = await session.get(Interview, old_terminal.session_id)
            active_row = await session.get(Interview, old_active.session_id)
            assert old_row is not None and active_row is not None
            old_timestamp = old_row.completed_at - timedelta(days=91)
            old_row.completed_at = old_timestamp
            old_row.updated_at = old_timestamp
            active_row.created_at = old_timestamp
            active_row.updated_at = old_timestamp

    summary = await cleanup_expired_interviews(retention_days=90)
    assert summary["interviews_deleted"] == 1
    assert await get_interview_by_buss_id(old_terminal.buss_id) is None
    assert await get_interview_by_buss_id(fresh_terminal.buss_id) is not None
    remaining_active = await get_interview_by_buss_id(old_active.buss_id)
    assert remaining_active is not None
    assert remaining_active.status == "joining"


@pytest.mark.asyncio
async def test_cascading_delete_removes_related_events_and_idempotency_keys(postgres_database):
    interview, _ = await _create_interview(
        buss_id="BUSS-CASCADE-1", idempotency_key="appointment-cascade-1"
    )
    await complete_interview(interview.session_id, "completed", {"result": "old"}, [])
    async with database_session() as session:
        async with session.begin():
            row = await session.get(Interview, interview.session_id)
            assert row is not None and row.completed_at is not None
            row.completed_at -= timedelta(days=91)

    await cleanup_expired_interviews(retention_days=90)
    async with database_session() as session:
        interview_result = await session.execute(
            select(Interview.session_id).where(Interview.session_id == interview.session_id)
        )
        event_result = await session.execute(
            select(InterviewEvent.id).where(InterviewEvent.session_id == interview.session_id)
        )
        key_result = await session.execute(
            select(IdempotencyKey.key_hash).where(IdempotencyKey.session_id == interview.session_id)
        )
    assert interview_result.scalar_one_or_none() is None
    assert event_result.scalar_one_or_none() is None
    assert key_result.scalar_one_or_none() is None
