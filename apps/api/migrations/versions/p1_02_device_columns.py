"""P1-02: device descriptive columns (all NULL) + device type asset_type/eos_date defaults

Revision ID: p1_02_device_columns
Revises: p1_01_default_site
"""
import sqlalchemy as sa
from alembic import op

from migrations.p0_common import NC, batch_keep_indexes

revision = "p1_02_device_columns"
down_revision = "p1_01_default_site"
branch_labels = None
depends_on = None

COLUMNS = [
    ("description", sa.Text()), ("notes", sa.Text()), ("asset_type", sa.String(64)), ("eos_date", sa.Date()),
    ("created_by", sa.String(128)), ("app_service", sa.String(128)), ("system_type", sa.String(64)),
    ("system_type_confidence", sa.String(16)), ("color_hex", sa.String(7)), ("power_assignment", sa.Text()),
    ("historic_name", sa.String(255)),
]
CHECKS = {
    "system_type_confidence": "system_type_confidence IS NULL OR system_type_confidence IN ('high','medium','low','unknown')",
    "color_hex": "color_hex IS NULL OR (length(color_hex) = 7 AND substr(color_hex, 1, 1) = '#')",
}


def upgrade() -> None:
    with batch_keep_indexes("devices") as batch:
        for name, type_ in COLUMNS:
            batch.add_column(sa.Column(name, type_, nullable=True))
        for name, sql in CHECKS.items():
            batch.create_check_constraint(name, sql)
    with op.batch_alter_table("device_types", naming_convention=NC) as batch:
        batch.add_column(sa.Column("asset_type", sa.String(64), nullable=True))
        batch.add_column(sa.Column("eos_date", sa.Date(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("device_types", naming_convention=NC) as batch:
        batch.drop_column("eos_date")
        batch.drop_column("asset_type")
    with batch_keep_indexes("devices") as batch:
        for name in CHECKS:
            batch.drop_constraint(op.f(f"ck_devices_{name}"), type_="check")
        for name, _ in reversed(COLUMNS):
            batch.drop_column(name)
