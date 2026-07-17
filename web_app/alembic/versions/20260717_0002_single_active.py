"""Enforce one active shared snapshot.

Revision ID: 20260717_0002
Revises: 20260717_0001
Create Date: 2026-07-17
"""
from alembic import op


revision = "20260717_0002"
down_revision = "20260717_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_datasets_single_published_shared "
        "ON datasets(status) WHERE kind = 'shared' AND status = 'published'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_datasets_single_published_shared")
