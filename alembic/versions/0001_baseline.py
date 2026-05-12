"""baseline — stamps existing schema, no DDL changes

Revision ID: 0001
Revises:
Create Date: 2026-05-06
"""
from __future__ import annotations

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass  # existing schema is already in place


def downgrade() -> None:
    pass
