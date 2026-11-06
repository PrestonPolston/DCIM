"""Design #2: devices.status server default 'active' -> 'install' (existing rows unchanged)

Revision ID: p1_09_status_default_install
Revises: p1_08_untyped_placement
"""
import sqlalchemy as sa

from migrations.p0_common import batch_keep_indexes

revision = "p1_09_status_default_install"
down_revision = "p1_08_untyped_placement"
branch_labels = None
depends_on = None


def _default(value: str) -> None:
    with batch_keep_indexes("devices") as batch:
        batch.alter_column("status", existing_type=sa.String(), existing_nullable=False,
                           server_default=sa.text(f"'{value}'"))


def upgrade() -> None:
    _default("install")


def downgrade() -> None:
    _default("active")
