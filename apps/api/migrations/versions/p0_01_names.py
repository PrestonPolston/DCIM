"""P0-01: name existing UNIQUE/FK constraints per the naming convention

Revision ID: p0_01_names
Revises: ab5579ca7488
"""
from alembic import op

from migrations.p0_common import NC

revision = "p0_01_names"
down_revision = "ab5579ca7488"
branch_labels = None
depends_on = None

# Rebuilding with naming_convention gives reflected unnamed constraints their NC names
# (no-op for databases created after the convention was introduced).
TABLES = ["halls", "rows", "racks", "device_types"]


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":  # Postgres DBs were created with names already
        for table in TABLES:
            with op.batch_alter_table(table, recreate="always", naming_convention=NC):
                pass
    with op.batch_alter_table("devices", recreate="auto", naming_convention=NC) as b:
        b.drop_constraint("fk_devices_rack_id", type_="foreignkey")
        b.drop_constraint("fk_devices_device_type_id", type_="foreignkey")
        b.create_foreign_key("fk_devices_rack_id_racks", "racks", ["rack_id"], ["id"])
        b.create_foreign_key("fk_devices_device_type_id_device_types", "device_types", ["device_type_id"], ["id"])


def downgrade() -> None:
    # names on halls/rows/racks/device_types are harmless; restore the old device FK names
    with op.batch_alter_table("devices", recreate="auto", naming_convention=NC) as b:
        b.drop_constraint("fk_devices_rack_id_racks", type_="foreignkey")
        b.drop_constraint("fk_devices_device_type_id_device_types", type_="foreignkey")
        b.create_foreign_key("fk_devices_rack_id", "racks", ["rack_id"], ["id"])
        b.create_foreign_key("fk_devices_device_type_id", "device_types", ["device_type_id"], ["id"])
