"""add lifecycle, content, and canonical_vacancy_id fields

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-06
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("jobs", sa.Column("grade", sa.String(32), nullable=True))
    op.add_column("jobs", sa.Column("salary_min", sa.Integer(), nullable=True))
    op.add_column("jobs", sa.Column("salary_max", sa.Integer(), nullable=True))
    op.add_column("jobs", sa.Column("salary_currency", sa.String(8), nullable=True))
    op.add_column("jobs", sa.Column("canonical_vacancy_id", sa.String(512), nullable=True))

    op.create_index("ix_jobs_first_seen_at", "jobs", ["first_seen_at"])
    op.create_index("ix_jobs_last_seen_at", "jobs", ["last_seen_at"])
    op.create_index("ix_jobs_closed_at", "jobs", ["closed_at"])
    op.create_index("ix_jobs_grade", "jobs", ["grade"])
    op.create_index("ix_jobs_canonical_vacancy_id", "jobs", ["canonical_vacancy_id"])

    # Backfill existing rows: treat created_at as first and last seen.
    op.execute("UPDATE jobs SET first_seen_at = created_at, last_seen_at = created_at")
    # Bootstrap canonical_vacancy_id from source_job_id.
    op.execute("UPDATE jobs SET canonical_vacancy_id = source_job_id")


def downgrade() -> None:
    op.drop_index("ix_jobs_canonical_vacancy_id", table_name="jobs")
    op.drop_index("ix_jobs_grade", table_name="jobs")
    op.drop_index("ix_jobs_closed_at", table_name="jobs")
    op.drop_index("ix_jobs_last_seen_at", table_name="jobs")
    op.drop_index("ix_jobs_first_seen_at", table_name="jobs")

    # SQLite requires batch mode to drop columns (handled by render_as_batch in env.py).
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_column("canonical_vacancy_id")
        batch_op.drop_column("salary_currency")
        batch_op.drop_column("salary_max")
        batch_op.drop_column("salary_min")
        batch_op.drop_column("grade")
        batch_op.drop_column("description")
        batch_op.drop_column("closed_at")
        batch_op.drop_column("last_seen_at")
        batch_op.drop_column("first_seen_at")
