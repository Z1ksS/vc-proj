"""add is_miltech flag to jobs

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-20
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

_MILTECH_PATTERNS = [
    "%miltech%", "%deftech%",
    "%military%", "%defence%", "%defense%",
    "% drone %", "%drone tech%", "%drone soft%",
    "% uav %", "% uas %", "%unmanned aerial%",
    "%weapon system%", "%weapons system%", "%ballistic%",
    "%warfighter%", "%battlefield management%",
    "%бпла%", "%безпілот%", "%оборонн%", "%військов%", "%зброй%",
]


def upgrade() -> None:
    op.add_column("jobs", sa.Column(
        "is_miltech", sa.Boolean(), nullable=False, server_default="0"
    ))
    op.create_index("ix_jobs_is_miltech", "jobs", ["is_miltech"])

    # Backfill existing records
    conn = op.get_bind()
    conditions = " OR ".join(
        f"lower(title) LIKE '{p}'"
        for p in _MILTECH_PATTERNS
    )
    conn.execute(sa.text(f"UPDATE jobs SET is_miltech = TRUE WHERE {conditions}"))


def downgrade() -> None:
    op.drop_index("ix_jobs_is_miltech", table_name="jobs")
    op.drop_column("jobs", "is_miltech")
