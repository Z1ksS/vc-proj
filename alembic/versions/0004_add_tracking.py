"""add tracking tables (users, columns, cards)

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-18
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("google_id", sa.String(128), nullable=False),
        sa.Column("email", sa.String(256), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("google_id", name="uq_users_google_id"),
    )
    op.create_index("ix_users_google_id", "users", ["google_id"], unique=True)

    op.create_table(
        "tracking_columns",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("color", sa.String(16), nullable=False, server_default="#4493f8"),
    )
    op.create_index("ix_tracking_columns_user_id", "tracking_columns", ["user_id"])

    op.create_table(
        "tracking_cards",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("column_id", sa.Integer(), sa.ForeignKey("tracking_columns.id"), nullable=False),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id"), nullable=True),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("company", sa.String(256), nullable=False, server_default=""),
        sa.Column("source", sa.String(64), nullable=False, server_default=""),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("stack_json", sa.Text(), nullable=True),
        sa.Column("salary_min", sa.Integer(), nullable=True),
        sa.Column("salary_max", sa.Integer(), nullable=True),
        sa.Column("salary_currency", sa.String(8), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("cover_letter", sa.Text(), nullable=True),
        sa.Column("cv_filename", sa.String(256), nullable=True),
        sa.Column("cv_path", sa.Text(), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("grade", sa.String(32), nullable=True),
        sa.Column("location", sa.String(256), nullable=True),
        sa.Column("events_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_tracking_cards_user_id", "tracking_cards", ["user_id"])
    op.create_index("ix_tracking_cards_column_id", "tracking_cards", ["column_id"])
    op.create_index("ix_tracking_cards_job_id", "tracking_cards", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_tracking_cards_job_id", table_name="tracking_cards")
    op.drop_index("ix_tracking_cards_column_id", table_name="tracking_cards")
    op.drop_index("ix_tracking_cards_user_id", table_name="tracking_cards")
    op.drop_table("tracking_cards")
    op.drop_index("ix_tracking_columns_user_id", table_name="tracking_columns")
    op.drop_table("tracking_columns")
    op.drop_index("ix_users_google_id", table_name="users")
    op.drop_table("users")
