"""Item 41: profile versions (version, supersedes_profile_id) and published_by. Schema only.

Revision ID: p1_17b_profile_versions
Revises: p1_17_profile_template
"""
import sqlalchemy as sa
from alembic import op

from migrations.p0_common import batch_keep_indexes

revision = "p1_17b_profile_versions"
down_revision = "p1_17_profile_template"
branch_labels = None
depends_on = None

TABLE = "device_type_profiles"


def upgrade() -> None:
    with batch_keep_indexes(TABLE) as batch:
        batch.add_column(sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("supersedes_profile_id", sa.Integer()))
        batch.add_column(sa.Column("published_by", sa.String(128)))
        batch.create_check_constraint("version", "version >= 1")
        batch.create_foreign_key("fk_device_type_profiles_supersedes", TABLE, ["supersedes_profile_id"], ["id"],
                                 ondelete="RESTRICT")
    op.create_index("ix_device_type_profiles_supersedes_profile_id", TABLE, ["supersedes_profile_id"])


def downgrade() -> None:
    op.drop_index("ix_device_type_profiles_supersedes_profile_id", table_name=TABLE)
    with batch_keep_indexes(TABLE) as batch:
        batch.drop_constraint("fk_device_type_profiles_supersedes", type_="foreignkey")
        batch.drop_constraint("version", type_="check")
        for col in ("published_by", "supersedes_profile_id", "version"):
            batch.drop_column(col)
