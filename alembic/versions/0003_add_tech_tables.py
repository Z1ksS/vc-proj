"""add technologies and vacancy_technologies tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-12
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "technologies",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.UniqueConstraint("name", name="uq_technologies_name"),
    )
    op.create_index("ix_technologies_name", "technologies", ["name"], unique=True)

    op.create_table(
        "vacancy_technologies",
        sa.Column("vacancy_id", sa.Integer(), sa.ForeignKey("jobs.id"), primary_key=True, nullable=False),
        sa.Column("tech_id", sa.Integer(), sa.ForeignKey("technologies.id"), primary_key=True, nullable=False),
    )
    op.create_index("ix_vacancy_technologies_tech_id", "vacancy_technologies", ["tech_id"])


def downgrade() -> None:
    op.drop_index("ix_vacancy_technologies_tech_id", table_name="vacancy_technologies")
    op.drop_table("vacancy_technologies")
    op.drop_index("ix_technologies_name", table_name="technologies")
    op.drop_table("technologies")
