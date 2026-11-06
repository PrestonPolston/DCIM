"""asset_type fixed list on device_types and devices (NULL = unknown; device NULL inherits from its type)

Free-text values are normalised (trim/lower, spaces and dashes to '_', a few synonyms); anything else
becomes 'other'. Nothing is deleted.

Revision ID: p1_16_asset_type_list
Revises: p1_15_profile_images
"""
import sqlalchemy as sa
from alembic import op

from migrations.p0_common import batch_keep_indexes

revision = "p1_16_asset_type_list"
down_revision = "p1_15_profile_images"
branch_labels = None
depends_on = None

VALUES = ("server", "switch", "patch_panel", "pdu", "router", "firewall", "storage", "blank", "shelf", "other")
SYNONYMS = {"patch": "patch_panel", "patchpanel": "patch_panel", "panel": "patch_panel", "blanking": "blank",
            "blank_panel": "blank", "blanking_panel": "blank", "san": "storage", "nas": "storage",
            "fw": "firewall", "servers": "server", "switches": "switch", "network_switch": "switch"}
CHECK = "asset_type IS NULL OR asset_type IN (" + ",".join(f"'{v}'" for v in VALUES) + ")"


def _normalise(table: str) -> None:
    conn = op.get_bind()
    t = sa.table(table, sa.column("id"), sa.column("asset_type"))
    for id_, raw in conn.execute(sa.select(t.c.id, t.c.asset_type).where(t.c.asset_type.is_not(None))).all():
        key = raw.strip().lower().replace(" ", "_").replace("-", "_")
        new = None if not key else (key if key in VALUES else SYNONYMS.get(key, "other"))
        if new != raw:
            conn.execute(t.update().where(t.c.id == id_).values(asset_type=new))


def upgrade() -> None:
    for table in ("device_types", "devices"):
        _normalise(table)
        with batch_keep_indexes(table) as batch:
            batch.alter_column("asset_type", type_=sa.String(32), existing_type=sa.String(64))
            batch.create_check_constraint("asset_type", CHECK)


def downgrade() -> None:
    for table in ("devices", "device_types"):
        with batch_keep_indexes(table) as batch:
            batch.drop_constraint("asset_type", type_="check")
            batch.alter_column("asset_type", type_=sa.String(64), existing_type=sa.String(32))
