"""P1-03: profile color_hex / airflow / power_type (null-tolerant CHECKs)

Revision ID: p1_03_profile_additions
Revises: p1_02_device_columns
"""
import sqlalchemy as sa
from alembic import op

from migrations.p0_common import batch_keep_indexes

revision = "p1_03_profile_additions"
down_revision = "p1_02_device_columns"
branch_labels = None
depends_on = None

CHECKS = {
    "color_hex": "color_hex IS NULL OR (length(color_hex) = 7 AND substr(color_hex, 1, 1) = '#')",
    "airflow": "airflow IS NULL OR airflow IN ('front_to_rear','rear_to_front','side','passive')",
    "power_type": "power_type IS NULL OR power_type IN ('AC','DC','AC_DC')",
}


def upgrade() -> None:
    with batch_keep_indexes("device_type_profiles") as batch:
        batch.add_column(sa.Column("color_hex", sa.String(7), nullable=True))
        batch.add_column(sa.Column("airflow", sa.String(16), nullable=True))
        batch.add_column(sa.Column("power_type", sa.String(8), nullable=True))
        for name, sql in CHECKS.items():
            batch.create_check_constraint(name, sql)


def downgrade() -> None:
    with batch_keep_indexes("device_type_profiles") as batch:
        for name in CHECKS:
            batch.drop_constraint(op.f(f"ck_device_type_profiles_{name}"), type_="check")
        for name in ("power_type", "airflow", "color_hex"):
            batch.drop_column(name)
