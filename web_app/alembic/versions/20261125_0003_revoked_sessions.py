"""Persist individual session revocations across processes and restarts."""
from alembic import op
from models import RevokedSession

revision = "20261125_0003"
down_revision = "20260717_0002"
branch_labels = None
depends_on = None


def upgrade():
    RevokedSession.__table__.create(op.get_bind(), checkfirst=True)


def downgrade():
    RevokedSession.__table__.drop(op.get_bind(), checkfirst=True)
