"""D58: device_type_profiles.orientation (port_front | power_front), nullable, no default, named CHECK.

Revision ID: p1_21_profile_orientation
Revises: p1_20_asset_type_cable_manager
"""
import sqlalchemy as sa
from alembic import op

from migrations.p0_common import batch_keep_indexes

revision = "p1_21_profile_orientation"
down_revision = "p1_20_asset_type_cable_manager"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with batch_keep_indexes("device_type_profiles") as batch:
        batch.add_column(sa.Column("orientation", sa.String(16)))
        batch.create_check_constraint("orientation", "orientation IS NULL OR orientation IN ('port_front','power_front')")


def downgrade() -> None:
    with batch_keep_indexes("device_type_profiles") as batch:
        batch.drop_constraint("orientation", type_="check")
        batch.drop_column("orientation")
