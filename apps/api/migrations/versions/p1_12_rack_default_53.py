"""Standard cabinet is 53 RU: racks.u_height server default 42 -> 53 (existing racks keep their height)

Revision ID: p1_12_rack_default_53
Revises: p1_11_serial_unavailable
"""
import sqlalchemy as sa
from alembic import op

from migrations.p0_common import batch_keep_indexes

revision = "p1_12_rack_default_53"
down_revision = "p1_11_serial_unavailable"
branch_labels = None
depends_on = None


def _default(value: str) -> None:
    with batch_keep_indexes("racks") as batch:
        batch.alter_column("u_height", existing_type=sa.Integer(), existing_nullable=False,
                           server_default=value)


def upgrade() -> None:
    _default("53")


def downgrade() -> None:
    _default("42")
