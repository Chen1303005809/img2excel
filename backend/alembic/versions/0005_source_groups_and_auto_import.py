"""add synchronized source groups and automatic import audit fields

Revision ID: 0005_source_groups_auto_import
Revises: 0004_force_recognition
Create Date: 2026-10-14
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_source_groups_auto_import"
down_revision = "0004_force_recognition"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_groups",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("future_source_id", sa.String(length=36), nullable=False),
        sa.Column("option_source_id", sa.String(length=36), nullable=False),
        sa.Column("schedule_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("schedule_interval_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["future_source_id"], ["sources.id"]),
        sa.ForeignKeyConstraint(["option_source_id"], ["sources.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("future_source_id"),
        sa.UniqueConstraint("option_source_id"),
    )

    op.create_table(
        "run_batches",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_group_id", sa.String(length=80), nullable=True),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("trigger_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("auto_import_status", sa.String(length=40), nullable=False),
        sa.Column("auto_import_message", sa.Text(), nullable=True),
        sa.Column("import_batch_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["source_group_id"], ["source_groups.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_run_batches_source_group_id", "run_batches", ["source_group_id"], unique=False)
    op.create_index("ix_run_batches_created", "run_batches", ["created_at"], unique=False)

    with op.batch_alter_table("runs") as batch_op:
        batch_op.add_column(sa.Column("run_batch_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key("fk_runs_run_batch_id", "run_batches", ["run_batch_id"], ["id"])
        batch_op.create_index("ix_runs_run_batch_id", ["run_batch_id"], unique=False)

    with op.batch_alter_table("database_import_batches") as batch_op:
        batch_op.add_column(sa.Column("run_batch_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("origin", sa.String(length=20), nullable=False, server_default="manual"))
        batch_op.add_column(
            sa.Column("replaced_template_ids", sa.JSON(), nullable=False, server_default="[]"),
        )
        batch_op.create_foreign_key("fk_database_import_batches_run_batch_id", "run_batches", ["run_batch_id"], ["id"])
        batch_op.create_index("ix_database_import_batches_run_batch_id", ["run_batch_id"], unique=False)

    op.create_table(
        "database_import_batch_runs",
        sa.Column("batch_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["database_import_batches.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
        sa.PrimaryKeyConstraint("batch_id", "run_id"),
    )
    op.create_index("ix_database_import_batch_runs_run", "database_import_batch_runs", ["run_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_database_import_batch_runs_run", table_name="database_import_batch_runs")
    op.drop_table("database_import_batch_runs")
    with op.batch_alter_table("database_import_batches") as batch_op:
        batch_op.drop_index("ix_database_import_batches_run_batch_id")
        batch_op.drop_constraint("fk_database_import_batches_run_batch_id", type_="foreignkey")
        batch_op.drop_column("replaced_template_ids")
        batch_op.drop_column("origin")
        batch_op.drop_column("run_batch_id")
    with op.batch_alter_table("runs") as batch_op:
        batch_op.drop_index("ix_runs_run_batch_id")
        batch_op.drop_constraint("fk_runs_run_batch_id", type_="foreignkey")
        batch_op.drop_column("run_batch_id")
    op.drop_index("ix_run_batches_created", table_name="run_batches")
    op.drop_index("ix_run_batches_source_group_id", table_name="run_batches")
    op.drop_table("run_batches")
    op.drop_table("source_groups")
