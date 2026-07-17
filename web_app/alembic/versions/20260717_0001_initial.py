"""Initial immutable datasets and analytics job schema.

Revision ID: 20260717_0001
Revises:
Create Date: 2026-07-17
"""
from __future__ import annotations

import sys
from pathlib import Path

from alembic import op


WEB_APP_DIR = Path(__file__).resolve().parents[2]
if str(WEB_APP_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_APP_DIR))

from models import Base


revision = "20260717_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
