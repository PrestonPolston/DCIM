"""D36/item 40: devices.profile_id NOT NULL (FK RESTRICT). Refuses, listing ids, while profile-less rows exist.

Run scripts/remove_profileless_devices.py first (operator-only, gated). This migration deletes nothing.

Revision ID: p1_18_device_profile_required
Revises: p1_19_removal_hardening
"""
import sqlalchemy as sa
from alembic import op

from migrations.p0_common import batch_keep_indexes

revision = "p1_18_device_profile_required"
down_revision = "p1_19_removal_hardening"
branch_labels = None
depends_on = None

FK = "fk_devices_profile_id_device_type_profiles"


def upgrade() -> None:
    rows = op.get_bind().execute(sa.text(
        "SELECT id, host_name FROM devices WHERE profile_id IS NULL ORDER BY id")).all()
    if rows:
        listed = ", ".join(f"{i} ({h})" for i, h in rows[:50]) + (" …" if len(rows) > 50 else "")
        raise RuntimeError(
            f"p1_18_device_profile_required: {len(rows)} device(s) have no profile: {listed}. Nothing was changed. "
            "Dry-run scripts/remove_profileless_devices.py (operator-only), resolve them, then upgrade again.")
    with batch_keep_indexes("devices") as batch:
        batch.drop_constraint(FK, type_="foreignkey")
        batch.alter_column("profile_id", existing_type=sa.Integer(), nullable=False)
        batch.create_foreign_key(FK, "device_type_profiles", ["profile_id"], ["id"], ondelete="RESTRICT")


def downgrade() -> None:
    with batch_keep_indexes("devices") as batch:
        batch.drop_constraint(FK, type_="foreignkey")
        batch.alter_column("profile_id", existing_type=sa.Integer(), nullable=True)
        batch.create_foreign_key(FK, "device_type_profiles", ["profile_id"], ["id"], ondelete="SET NULL")
