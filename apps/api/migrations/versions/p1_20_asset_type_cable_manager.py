"""asset_type list gets an 11th value, cable_manager (device_types and devices CHECK).

Downgrade maps cable_manager rows to 'other' first (the old CHECK would reject them) and says how many.

Revision ID: p1_20_asset_type_cable_manager
Revises: p1_18_device_profile_required
"""
import sqlalchemy as sa
from alembic import op

from migrations.p0_common import batch_keep_indexes

revision = "p1_20_asset_type_cable_manager"
down_revision = "p1_18_device_profile_required"
branch_labels = None
depends_on = None

OLD = ("server", "switch", "patch_panel", "pdu", "router", "firewall", "storage", "blank", "shelf", "other")
NEW = OLD[:-1] + ("cable_manager", "other")


def _check(values) -> str:
    return "asset_type IS NULL OR asset_type IN (" + ",".join(f"'{v}'" for v in values) + ")"


def _swap(values) -> None:
    for table in ("device_types", "devices"):
        with batch_keep_indexes(table) as batch:
            batch.drop_constraint("asset_type", type_="check")
            batch.create_check_constraint("asset_type", _check(values))


def upgrade() -> None:
    _swap(NEW)


def downgrade() -> None:
    conn = op.get_bind()
    for table in ("device_types", "devices"):
        n = conn.execute(sa.text(f"UPDATE {table} SET asset_type = 'other' WHERE asset_type = 'cable_manager'")).rowcount
        if n:
            print(f"p1_20 downgrade: {n} {table} row(s) cable_manager -> other")
    _swap(OLD)
