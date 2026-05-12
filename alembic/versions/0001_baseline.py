"""baseline — create initial jobs table

Revision ID: 0001
Revises:
Create Date: 2026-05-06
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("source_job_id", sa.String(512), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("company", sa.String(256), nullable=False),
        sa.Column("salary", sa.String(256), nullable=False, server_default=""),
        sa.Column("link", sa.Text(), nullable=False),
        sa.Column("job_format", sa.String(256), nullable=False, server_default=""),
        sa.Column("normalized_title", sa.String(256), nullable=False),
        sa.Column("normalized_company", sa.String(256), nullable=False),
        sa.Column("dedupe_fingerprint", sa.String(512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("source_job_id", name="uq_jobs_source_job_id"),
    )
    op.create_index("ix_jobs_source", "jobs", ["source"])
    op.create_index("ix_jobs_title", "jobs", ["title"])
    op.create_index("ix_jobs_company", "jobs", ["company"])
    op.create_index("ix_jobs_normalized_title", "jobs", ["normalized_title"])
    op.create_index("ix_jobs_normalized_company", "jobs", ["normalized_company"])
    op.create_index("ix_jobs_dedupe_fingerprint", "jobs", ["dedupe_fingerprint"])
    op.create_index("ix_jobs_dedupe_source", "jobs", ["dedupe_fingerprint", "source"])


def downgrade() -> None:
    op.drop_index("ix_jobs_dedupe_source", table_name="jobs")
    op.drop_index("ix_jobs_dedupe_fingerprint", table_name="jobs")
    op.drop_index("ix_jobs_normalized_company", table_name="jobs")
    op.drop_index("ix_jobs_normalized_title", table_name="jobs")
    op.drop_index("ix_jobs_company", table_name="jobs")
    op.drop_index("ix_jobs_title", table_name="jobs")
    op.drop_index("ix_jobs_source", table_name="jobs")
    op.drop_table("jobs")
