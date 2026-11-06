"""P1-05: devices.owner free text (D13) + lower(owner) index

Revision ID: p1_05_owner
Revises: p1_04_groups
"""
import sqlalchemy as sa
from alembic import op

from migrations.p0_common import batch_keep_indexes

revision = "p1_05_owner"
down_revision = "p1_04_groups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with batch_keep_indexes("devices") as batch:
        batch.add_column(sa.Column("owner", sa.String(255), nullable=True))
        batch.create_check_constraint("owner_nonempty", "owner IS NULL OR length(trim(owner)) > 0")
    op.create_index("ix_devices_owner_lower", "devices", [sa.text("lower(owner)")])


def downgrade() -> None:
    op.drop_index("ix_devices_owner_lower", table_name="devices")
    with batch_keep_indexes("devices") as batch:
        batch.drop_constraint(op.f("ck_devices_owner_nonempty"), type_="check")
        batch.drop_column("owner")
