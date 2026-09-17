"""add source schedules and recognition skip marker

Revision ID: 0002_schedules_and_recognition_skip
Revises: 0001_initial
Create Date: 2026-09-17
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_schedules_and_recognition_skip"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sources",
        sa.Column("schedule_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "sources",
        sa.Column("schedule_interval_minutes", sa.Integer(), nullable=False, server_default="60"),
    )
    op.add_column("sources", sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "runs",
        sa.Column("recognition_skipped", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("runs", "recognition_skipped")
    op.drop_column("sources", "next_run_at")
    op.drop_column("sources", "schedule_interval_minutes")
    op.drop_column("sources", "schedule_enabled")
