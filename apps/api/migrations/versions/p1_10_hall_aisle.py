"""Designer: halls.aisle_axis / odd_side floor-plan hints (nullable)

Revision ID: p1_10_hall_aisle
Revises: p1_09_status_default_install
"""
import sqlalchemy as sa
from alembic import op

from migrations.p0_common import batch_keep_indexes

revision = "p1_10_hall_aisle"
down_revision = "p1_09_status_default_install"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with batch_keep_indexes("halls") as batch:
        batch.add_column(sa.Column("aisle_axis", sa.String(1), nullable=True))
        batch.add_column(sa.Column("odd_side", sa.String(4), nullable=True))
        batch.create_check_constraint("aisle_axis", "aisle_axis IS NULL OR aisle_axis IN ('x','y')")
        batch.create_check_constraint("odd_side", "odd_side IS NULL OR odd_side IN ('low','high')")


def downgrade() -> None:
    with batch_keep_indexes("halls") as batch:
        batch.drop_constraint(op.f("ck_halls_odd_side"), type_="check")
        batch.drop_constraint(op.f("ck_halls_aisle_axis"), type_="check")
        batch.drop_column("odd_side")
        batch.drop_column("aisle_axis")
