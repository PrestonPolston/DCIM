"""P1-04: managed-by groups (unique lower(name))

Revision ID: p1_04_groups
Revises: p1_03_profile_additions
"""
import sqlalchemy as sa
from alembic import op

from migrations.p0_common import timestamp_cols

revision = "p1_04_groups"
down_revision = "p1_03_profile_additions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        *timestamp_cols(),
        sa.PrimaryKeyConstraint("id", name="pk_groups"),
    )
    op.create_index("uq_groups_name", "groups", [sa.text("lower(name)")], unique=True)


def downgrade() -> None:
    op.drop_index("uq_groups_name", table_name="groups")
    op.drop_table("groups")
