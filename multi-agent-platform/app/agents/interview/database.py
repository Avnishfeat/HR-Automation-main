"""PostgreSQL persistence for Interview Agent lifecycle and final reports."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import logging
from typing import Any, AsyncIterator, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, delete, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.agents.interview.config.constants import InterruptionReason, SessionStatus
from app.core.config import settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


class Interview(Base):
    __tablename__ = "interviews"

    session_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    buss_id: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    candidate_email: Mapped[str] = mapped_column(String(320), nullable=False)
    job_role: Mapped[str] = mapped_column(String(500), nullable=False)
    job_description: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    terminal_reason: Mapped[Optional[str]] = mapped_column(String(128))
    analysis_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    agent_errors: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class InterviewEvent(Base):
    __tablename__ = "interview_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("interviews.session_id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class IdempotencyKey(Base):
    __tablename__ = "interview_idempotency_keys"

    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("interviews.session_id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class InterviewArtifact(Base):
    __tablename__ = "interview_artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("interviews.session_id", ondelete="CASCADE"), index=True)
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


_engine = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _key_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def initialize_database() -> None:
    global _engine, _session_factory
    if _session_factory is not None:
        return
    if not settings.DATABASE_URL:
        raise RuntimeError("DATABASE_URL must be configured for Interview Agent persistence")
    _engine = create_async_engine(
        settings.DATABASE_URL,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        connect_args={"timeout": settings.DATABASE_CONNECT_TIMEOUT_SEC},
    )
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    async with _engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
    logger.info("Interview PostgreSQL connection initialized")


async def close_database() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


@asynccontextmanager
async def database_session() -> AsyncIterator[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("Interview database has not been initialized")
    async with _session_factory() as session:
        yield session


async def database_is_healthy() -> bool:
    try:
        async with database_session() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.exception("Interview database health check failed")
        return False


async def get_interview_by_buss_id(buss_id: str) -> Optional[Interview]:
    async with database_session() as session:
        return await session.scalar(select(Interview).where(Interview.buss_id == buss_id))


async def get_interview_by_idempotency_key(key: str) -> Optional[Interview]:
    async with database_session() as session:
        statement = (
            select(Interview)
            .join(IdempotencyKey, IdempotencyKey.session_id == Interview.session_id)
            .where(IdempotencyKey.key_hash == _key_hash(key), IdempotencyKey.expires_at > _utcnow())
        )
        return await session.scalar(statement)


async def create_or_get_interview(
    *,
    session_id: str,
    buss_id: str,
    candidate_email: str,
    job_role: str,
    job_description: Optional[str],
    idempotency_key: Optional[str],
) -> tuple[Interview, bool]:
    """Create an interview once, returning the existing row for safe retries."""
    now = _utcnow()
    async with database_session() as session:
        try:
            async with session.begin():
                existing = await session.scalar(select(Interview).where(Interview.buss_id == buss_id))
                if existing:
                    return existing, False
                if idempotency_key:
                    existing = await session.scalar(
                        select(Interview)
                        .join(IdempotencyKey, IdempotencyKey.session_id == Interview.session_id)
                        .where(IdempotencyKey.key_hash == _key_hash(idempotency_key), IdempotencyKey.expires_at > now)
                    )
                    if existing:
                        return existing, False
                interview = Interview(
                    session_id=session_id,
                    buss_id=buss_id,
                    candidate_email=candidate_email,
                    job_role=job_role,
                    job_description=job_description,
                    status="pending",
                    created_at=now,
                    updated_at=now,
                    agent_errors=[],
                )
                session.add(interview)
                # Ensure the parent exists before dependent event and
                # idempotency-key rows are flushed. This matters because the
                # models intentionally use scalar FK fields rather than ORM
                # relationship objects.
                await session.flush()
                session.add(InterviewEvent(session_id=session_id, event_type="created", status="pending", details={}, created_at=now))
                if idempotency_key:
                    session.add(IdempotencyKey(
                        key_hash=_key_hash(idempotency_key), session_id=session_id, created_at=now,
                        expires_at=now + timedelta(days=settings.IDEMPOTENCY_KEY_RETENTION_DAYS),
                    ))
                return interview, True
        except IntegrityError:
            await session.rollback()
            existing = await session.scalar(select(Interview).where(Interview.buss_id == buss_id))
            if existing:
                return existing, False
            if idempotency_key:
                existing = await get_interview_by_idempotency_key(idempotency_key)
                if existing:
                    return existing, False
            raise


async def update_interview_status(session_id: str, status: str, details: Optional[dict[str, Any]] = None) -> None:
    now = _utcnow()
    async with database_session() as session, session.begin():
        interview = await session.get(Interview, session_id)
        if not interview:
            return
        interview.status = status
        interview.updated_at = now
        if status == "interviewing" and interview.started_at is None:
            interview.started_at = now
        session.add(InterviewEvent(session_id=session_id, event_type="status", status=status, details=details or {}, created_at=now))


async def complete_interview(
    session_id: str,
    status: str,
    analysis: Optional[dict[str, Any]],
    agent_errors: list[dict[str, Any]],
    terminal_reason: Optional[str] = None,
) -> None:
    now = _utcnow()
    async with database_session() as session, session.begin():
        interview = await session.get(Interview, session_id)
        if not interview:
            return
        interview.status = status
        resolved_reason = terminal_reason if terminal_reason is not None else (
            status if status != "completed" else None
        )
        interview.terminal_reason = resolved_reason
        interview.analysis_json = analysis
        interview.agent_errors = agent_errors
        interview.completed_at = now
        interview.updated_at = now
        event_type = "interrupted" if status == "interrupted" else "completed"
        event_details = {"has_analysis": analysis is not None}
        if resolved_reason:
            event_details["reason"] = resolved_reason
        session.add(
            InterviewEvent(
                session_id=session_id,
                event_type=event_type,
                status=status,
                details=event_details,
                created_at=now,
            )
        )


async def mark_orphaned_interviews() -> int:
    active_statuses = ("pending", "joining", "interviewing", "analyzing")
    now = _utcnow()
    async with database_session() as session, session.begin():
        rows = (await session.scalars(select(Interview).where(Interview.status.in_(active_statuses)))).all()
        for interview in rows:
            interview.status = SessionStatus.INTERRUPTED
            interview.terminal_reason = InterruptionReason.BACKEND_RESTARTED
            interview.completed_at = now
            interview.updated_at = now
            session.add(
                InterviewEvent(
                    session_id=interview.session_id,
                    event_type="interrupted",
                    status=SessionStatus.INTERRUPTED,
                    details={"reason": InterruptionReason.BACKEND_RESTARTED},
                    created_at=now,
                )
            )
        return len(rows)


async def delete_pending_interview(session_id: str) -> None:
    """Remove a record only when scheduling failed before its task was created."""
    async with database_session() as session, session.begin():
        interview = await session.get(Interview, session_id)
        if interview and interview.status == "pending":
            await session.delete(interview)


async def cleanup_expired_interviews(retention_days: Optional[int] = None) -> dict[str, int]:
    """Delete only terminal interview records beyond the configured retention window.

    Foreign keys cascade to the corresponding event, idempotency-key, and artifact
    records. Active and incomplete interviews are deliberately never eligible.
    """
    if retention_days is None:
        retention_days = settings.INTERVIEW_RECORD_RETENTION_DAYS
    retention_days = max(0, retention_days)
    cutoff = _utcnow() - timedelta(days=retention_days)
    terminal_statuses = (
        "completed", "completed_no_analysis", "time_limit_reached", "interrupted",
        "error_capacity_reached", "error_join_failed", "error_candidate_no_show",
        "error_candidate_left", "error_multiple_participants", "error_analysis_empty",
        "error_analysis_failed", "error_fatal_task", "terminated_liveness_fail",
        "aborted_multiple_participants", "aborted_multiple_participants_timeout",
    )
    async with database_session() as session, session.begin():
        result = await session.execute(
            delete(Interview).where(
                Interview.status.in_(terminal_statuses),
                Interview.completed_at.is_not(None),
                Interview.completed_at <= cutoff,
            )
        )
    deleted = result.rowcount if result.rowcount is not None and result.rowcount >= 0 else 0
    return {"interviews_deleted": deleted, "skipped": 0}


def normalize_idempotency_key(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    key = value.strip()
    if not key or len(key) > 256 or any(not character.isprintable() for character in key):
        raise ValueError("X-Idempotency-Key must be 1-256 printable characters")
    return key
