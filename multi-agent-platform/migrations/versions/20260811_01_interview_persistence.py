"""Create PostgreSQL persistence for interview retrieval.

Revision ID: 20260811_01
Revises:
Create Date: 2026-08-11
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260811_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "interviews",
        sa.Column("session_id", sa.String(length=36), primary_key=True),
        sa.Column("buss_id", sa.String(length=255), nullable=False, unique=True),
        sa.Column("candidate_email", sa.String(length=320), nullable=False),
        sa.Column("job_role", sa.String(length=500), nullable=False),
        sa.Column("job_description", sa.Text()),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("terminal_reason", sa.String(length=128)),
        sa.Column("analysis_json", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("agent_errors", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_interviews_buss_id", "interviews", ["buss_id"])
    op.create_index("ix_interviews_status", "interviews", ["status"])
    op.create_index("ix_interviews_completed_at", "interviews", ["completed_at"])
    op.create_table(
        "interview_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(length=36), sa.ForeignKey("interviews.session_id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_interview_events_session_id", "interview_events", ["session_id"])
    op.create_table(
        "interview_idempotency_keys",
        sa.Column("key_hash", sa.String(length=64), primary_key=True),
        sa.Column("session_id", sa.String(length=36), sa.ForeignKey("interviews.session_id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_interview_idempotency_keys_session_id", "interview_idempotency_keys", ["session_id"])
    op.create_index("ix_interview_idempotency_keys_expires_at", "interview_idempotency_keys", ["expires_at"])
    op.create_table(
        "interview_artifacts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(length=36), sa.ForeignKey("interviews.session_id", ondelete="CASCADE"), nullable=False),
        sa.Column("artifact_type", sa.String(length=64), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_interview_artifacts_session_id", "interview_artifacts", ["session_id"])


def downgrade() -> None:
    op.drop_table("interview_artifacts")
    op.drop_table("interview_idempotency_keys")
    op.drop_table("interview_events")
    op.drop_table("interviews")
