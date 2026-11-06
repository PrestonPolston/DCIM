"""Item 49: devices.needs_review / needs_review_reason (schema only; flags are set by p1_17, nothing deleted)

Revision ID: p1_14_needs_review
Revises: p1_13_connections
"""
import sqlalchemy as sa
from alembic import op

from migrations.p0_common import batch_keep_indexes

revision = "p1_14_needs_review"
down_revision = "p1_13_connections"
branch_labels = None
depends_on = None

REASONS = "needs_review_reason IS NULL OR needs_review_reason IN ('placed_without_profile','profile_not_published','other')"


def upgrade() -> None:
    with batch_keep_indexes("devices") as batch:
        batch.add_column(sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("needs_review_reason", sa.String(32)))
        batch.create_check_constraint("needs_review_reason", REASONS)
        batch.create_check_constraint("needs_review", "needs_review = (needs_review_reason IS NOT NULL)")
    op.create_index("ix_devices_needs_review", "devices", ["needs_review"],
                    sqlite_where=sa.text("needs_review"), postgresql_where=sa.text("needs_review"))


def downgrade() -> None:
    op.drop_index("ix_devices_needs_review", table_name="devices")
    with batch_keep_indexes("devices") as batch:
        batch.drop_constraint("needs_review", type_="check")
        batch.drop_constraint("needs_review_reason", type_="check")
        batch.drop_column("needs_review_reason")
        batch.drop_column("needs_review")
