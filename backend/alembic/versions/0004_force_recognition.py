"""add force recognition marker to runs

Revision ID: 0004_force_recognition
Revises: 0003_database_imports
Create Date: 2026-09-28
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_force_recognition"
down_revision = "0003_database_imports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column("force_recognition", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("runs", "force_recognition")
