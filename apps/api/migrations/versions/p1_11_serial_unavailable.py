"""Design #3: devices.serial_unavailable (bool, default false) + serial_note

Revision ID: p1_11_serial_unavailable
Revises: p1_10_hall_aisle
"""
import sqlalchemy as sa
from alembic import op

from migrations.p0_common import batch_keep_indexes, precheck

revision = "p1_11_serial_unavailable"
down_revision = "p1_10_hall_aisle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with batch_keep_indexes("devices") as batch:
        batch.add_column(sa.Column("serial_unavailable", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("serial_note", sa.String(128), nullable=True))
        batch.create_check_constraint("serial_unavailable", "NOT serial_unavailable OR serial_number IS NULL")


def downgrade() -> None:
    with batch_keep_indexes("devices") as batch:
        batch.drop_constraint(op.f("ck_devices_serial_unavailable"), type_="check")
        batch.drop_column("serial_note")
        batch.drop_column("serial_unavailable")
