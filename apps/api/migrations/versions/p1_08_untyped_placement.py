"""Design #1: a device may be racked without a device type (Unknown type = 1U, both faces)

Relaxes ck_devices_placement: rack_id and position_u still go together; device_type_id is optional.

Revision ID: p1_08_untyped_placement
Revises: p1_07_name_history
"""
from alembic import op

from migrations.p0_common import batch_keep_indexes, precheck

revision = "p1_08_untyped_placement"
down_revision = "p1_07_name_history"
branch_labels = None
depends_on = None

NEW = "(rack_id IS NULL AND position_u IS NULL) OR (rack_id IS NOT NULL AND position_u IS NOT NULL)"
OLD = ("(rack_id IS NULL AND position_u IS NULL) OR "
       "(rack_id IS NOT NULL AND position_u IS NOT NULL AND device_type_id IS NOT NULL)")


def _swap(sql: str) -> None:
    with batch_keep_indexes("devices") as batch:
        batch.drop_constraint(op.f("ck_devices_placement"), type_="check")
        batch.create_check_constraint("placement", sql)


def upgrade() -> None:
    _swap(NEW)


def downgrade() -> None:
    precheck([("racked devices without a device type (unrack or set a type first)",
               "SELECT id FROM devices WHERE rack_id IS NOT NULL AND device_type_id IS NULL")])
    _swap(OLD)
