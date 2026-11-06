"""P1-07: device_name_history

Revision ID: p1_07_name_history
Revises: p1_06_projects
"""
import sqlalchemy as sa
from alembic import op

revision = "p1_07_name_history"
down_revision = "p1_06_projects"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "device_name_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("old_name", sa.String(253), nullable=False),
        sa.Column("new_name", sa.String(253), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("changed_by", sa.String()),
        sa.Column("change_set_id", sa.Integer()),
        sa.PrimaryKeyConstraint("id", name="pk_device_name_history"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], name="fk_device_name_history_device_id_devices",
                                ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["change_set_id"], ["change_sets.id"],
                                name="fk_device_name_history_change_set_id_change_sets", ondelete="RESTRICT"),
    )
    op.create_index("ix_device_name_history_device_id_changed_at", "device_name_history", ["device_id", "changed_at"])
    op.create_index("ix_device_name_history_old_name_lower", "device_name_history", [sa.text("lower(old_name)")])


def downgrade() -> None:
    op.drop_table("device_name_history")
