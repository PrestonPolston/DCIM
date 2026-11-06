"""P0-07: host name unique per rack (case-insensitive, live racked devices)

Revision ID: p0_07_hostname_unique
Revises: p0_06_history
"""
import sqlalchemy as sa
from alembic import op

from migrations.p0_common import precheck

revision = "p0_07_hostname_unique"
down_revision = "p0_06_history"
branch_labels = None
depends_on = None

SCOPE = "rack_id IS NOT NULL AND deleted_at IS NULL"


def upgrade() -> None:
    precheck([(
        "devices sharing a host name within one rack",
        f"SELECT min(id) FROM devices WHERE {SCOPE} GROUP BY rack_id, lower(host_name) HAVING count(*) > 1",
    )])
    op.create_index(
        "uq_devices_rack_id_host_name", "devices", ["rack_id", sa.text("lower(host_name)")], unique=True,
        sqlite_where=sa.text(SCOPE), postgresql_where=sa.text(SCOPE),
    )


def downgrade() -> None:
    op.drop_index("uq_devices_rack_id_host_name", table_name="devices")
