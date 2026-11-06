"""P0-04: created_at/updated_at everywhere, soft delete on racks/devices, device lifecycle timestamps

Revision ID: p0_04_timestamps_soft_delete
Revises: p0_03_checks
"""
import sqlalchemy as sa
from alembic import op

from migrations.p0_common import NC, timestamp_cols

revision = "p0_04_timestamps_soft_delete"
down_revision = "p0_03_checks"
branch_labels = None
depends_on = None

TABLES = ["sites", "halls", "rows", "racks", "device_types", "devices"]
SOFT = ["racks", "devices"]
LIFECYCLE = ["status_changed_at", "installed_at", "activated_at", "decommissioned_at"]
LIVE = sa.text("deleted_at IS NULL")


def upgrade() -> None:
    for table in TABLES:
        with op.batch_alter_table(table, naming_convention=NC) as b:
            for col in timestamp_cols():  # existing rows get the migration time
                b.add_column(col)
            if table in SOFT:
                b.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
                b.add_column(sa.Column("deleted_by", sa.String(), nullable=True))
                b.create_index(f"ix_{table}_deleted_at", ["deleted_at"])
            if table == "devices":
                for name in LIFECYCLE:
                    b.add_column(sa.Column(name, sa.DateTime(timezone=True), nullable=True))
            if table == "racks":
                b.drop_constraint("uq_racks_row_id_name", type_="unique")
    op.create_index(
        "uq_racks_row_id_name", "racks", ["row_id", "name"], unique=True,
        sqlite_where=LIVE, postgresql_where=LIVE,
    )


def downgrade() -> None:
    op.drop_index("uq_racks_row_id_name", table_name="racks")
    for table in reversed(TABLES):
        with op.batch_alter_table(table, naming_convention=NC) as b:
            if table == "racks":
                b.create_unique_constraint("uq_racks_row_id_name", ["row_id", "name"])
            if table == "devices":
                for name in LIFECYCLE:
                    b.drop_column(name)
            if table in SOFT:
                b.drop_index(f"ix_{table}_deleted_at")
                b.drop_column("deleted_by")
                b.drop_column("deleted_at")
            b.drop_column("updated_at")
            b.drop_column("created_at")
