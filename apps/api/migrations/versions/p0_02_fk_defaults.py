"""P0-02: explicit ON DELETE RESTRICT on FKs, server defaults

Revision ID: p0_02_fk_defaults
Revises: p0_01_names
"""
import sqlalchemy as sa
from alembic import op

from migrations.p0_common import NC

revision = "p0_02_fk_defaults"
down_revision = "p0_01_names"
branch_labels = None
depends_on = None

FKS = [  # table, column, referred
    ("halls", "site_id", "sites"),
    ("rows", "hall_id", "halls"),
    ("racks", "row_id", "rows"),
    ("devices", "device_type_id", "device_types"),
    ("devices", "rack_id", "racks"),
]


def _set_fks(table: str, b, ondelete: str | None) -> None:
    for t, col, ref in FKS:
        if t == table:
            name = f"fk_{t}_{col}_{ref}"
            b.drop_constraint(name, type_="foreignkey")
            b.create_foreign_key(name, ref, [col], ["id"], ondelete=ondelete)


def upgrade() -> None:
    for table in ["halls", "rows"]:
        with op.batch_alter_table(table, recreate="auto", naming_convention=NC) as b:
            _set_fks(table, b, "RESTRICT")
    with op.batch_alter_table("racks", recreate="auto", naming_convention=NC) as b:
        _set_fks("racks", b, "RESTRICT")
        b.alter_column("u_height", existing_type=sa.Integer(), server_default="42")
    with op.batch_alter_table("device_types", recreate="auto", naming_convention=NC) as b:
        b.alter_column("u_height", existing_type=sa.Integer(), server_default="1")
        b.alter_column("is_full_depth", existing_type=sa.Boolean(), server_default=sa.true())
    with op.batch_alter_table("devices", recreate="auto", naming_convention=NC) as b:
        _set_fks("devices", b, "RESTRICT")
        b.alter_column("status", existing_type=sa.String(), server_default="active")


def downgrade() -> None:
    with op.batch_alter_table("devices", recreate="auto", naming_convention=NC) as b:
        _set_fks("devices", b, None)
        b.alter_column("status", existing_type=sa.String(), server_default=None)
    with op.batch_alter_table("device_types", recreate="auto", naming_convention=NC) as b:
        b.alter_column("u_height", existing_type=sa.Integer(), server_default=None)
        b.alter_column("is_full_depth", existing_type=sa.Boolean(), server_default=None)
    with op.batch_alter_table("racks", recreate="auto", naming_convention=NC) as b:
        _set_fks("racks", b, None)
        b.alter_column("u_height", existing_type=sa.Integer(), server_default=None)
    for table in ["rows", "halls"]:
        with op.batch_alter_table(table, recreate="auto", naming_convention=NC) as b:
            _set_fks(table, b, None)
