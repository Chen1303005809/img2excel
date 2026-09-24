"""add database import audit tables

Revision ID: 0003_database_imports
Revises: 0002_schedules_and_recognition_skip
Create Date: 2026-09-24
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_database_imports"
down_revision = "0002_schedules_and_recognition_skip"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "database_import_batches",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("revision_id", sa.String(length=36), nullable=True),
        sa.Column("view", sa.String(length=20), nullable=False),
        sa.Column("template_type", sa.String(length=128), nullable=False),
        sa.Column("template_name", sa.String(length=100), nullable=False),
        sa.Column("source_document_sha256", sa.String(length=64), nullable=False),
        sa.Column("entity_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("counts", sa.JSON(), nullable=False),
        sa.Column("used_derived_warning", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("target_template_ids", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["revision_id"], ["document_revisions.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id",
            "source_document_sha256",
            "template_type",
            "entity_fingerprint",
            name="uq_database_import_batch_fingerprint",
        ),
    )
    op.create_index("ix_database_import_batches_run_id", "database_import_batches", ["run_id"], unique=False)
    op.create_index("ix_database_import_batches_revision_id", "database_import_batches", ["revision_id"], unique=False)
    op.create_index("ix_database_import_batches_status", "database_import_batches", ["status"], unique=False)
    op.create_index(
        "ix_database_import_batches_run_created",
        "database_import_batches",
        ["run_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_database_import_batches_status_created",
        "database_import_batches",
        ["status", "created_at"],
        unique=False,
    )

    op.create_table(
        "database_import_issues",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("batch_id", sa.String(length=36), nullable=False),
        sa.Column("entity_type", sa.String(length=40), nullable=False),
        sa.Column("entity_index", sa.Integer(), nullable=False),
        sa.Column("field", sa.String(length=80), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("source_cells", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["database_import_batches.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_database_import_issues_batch_id", "database_import_issues", ["batch_id"], unique=False)
    op.create_index(
        "ix_database_import_issues_batch",
        "database_import_issues",
        ["batch_id", "entity_index"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_database_import_issues_batch", table_name="database_import_issues")
    op.drop_index("ix_database_import_issues_batch_id", table_name="database_import_issues")
    op.drop_table("database_import_issues")
    op.drop_index("ix_database_import_batches_status_created", table_name="database_import_batches")
    op.drop_index("ix_database_import_batches_run_created", table_name="database_import_batches")
    op.drop_index("ix_database_import_batches_status", table_name="database_import_batches")
    op.drop_index("ix_database_import_batches_revision_id", table_name="database_import_batches")
    op.drop_index("ix_database_import_batches_run_id", table_name="database_import_batches")
    op.drop_table("database_import_batches")
