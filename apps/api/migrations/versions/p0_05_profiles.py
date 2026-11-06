"""P0-05: device_type_profiles (one default per type) + devices.profile_id

Revision ID: p0_05_profiles
Revises: p0_04_timestamps_soft_delete
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from migrations.p0_common import NC, timestamp_cols

revision = "p0_05_profiles"
down_revision = "p0_04_timestamps_soft_delete"
branch_labels = None
depends_on = None

JSONType = sa.JSON().with_variant(JSONB, "postgresql")


def upgrade() -> None:
    op.create_table(
        "device_type_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_type_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("u_height", sa.Integer(), nullable=False),
        sa.Column("width_mm", sa.Numeric(), nullable=True),
        sa.Column("height_mm", sa.Numeric(), nullable=True),
        sa.Column("depth_mm", sa.Numeric(), nullable=True),
        sa.Column("is_full_depth", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("faces", JSONType, nullable=False, server_default=sa.text("'[\"front\",\"rear\"]'")),
        sa.Column("ports", JSONType, nullable=True),
        sa.Column("power", JSONType, nullable=True),
        sa.Column("model_refs", JSONType, nullable=True),
        *timestamp_cols(),
        sa.PrimaryKeyConstraint("id", name="pk_device_type_profiles"),
        sa.ForeignKeyConstraint(
            ["device_type_id"], ["device_types.id"], ondelete="CASCADE",
            name="fk_device_type_profiles_device_type_id_device_types",
        ),
        sa.UniqueConstraint("device_type_id", "name", name="uq_device_type_profiles_device_type_id_name"),
        sa.CheckConstraint("u_height BETWEEN 0 AND 100", name="ck_device_type_profiles_u_height"),
        sa.CheckConstraint(
            "(width_mm IS NULL OR width_mm > 0) AND (height_mm IS NULL OR height_mm > 0) "
            "AND (depth_mm IS NULL OR depth_mm > 0)",
            name="ck_device_type_profiles_dims",
        ),
    )
    op.create_index("ix_device_type_profiles_device_type_id", "device_type_profiles", ["device_type_id"])
    op.create_index(
        "uq_device_type_profiles_default", "device_type_profiles", ["device_type_id"], unique=True,
        sqlite_where=sa.text("is_default"), postgresql_where=sa.text("is_default"),
    )
    # one default profile per existing device type
    op.execute(
        "INSERT INTO device_type_profiles (device_type_id, name, is_default, u_height, is_full_depth) "
        "SELECT id, 'default', true, u_height, is_full_depth FROM device_types"
    )
    with op.batch_alter_table("devices", naming_convention=NC) as b:
        b.add_column(sa.Column("profile_id", sa.Integer(), nullable=True))
        b.create_foreign_key(
            "fk_devices_profile_id_device_type_profiles", "device_type_profiles",
            ["profile_id"], ["id"], ondelete="SET NULL",
        )
        b.create_index("ix_devices_profile_id", ["profile_id"])


def downgrade() -> None:
    with op.batch_alter_table("devices", naming_convention=NC) as b:
        b.drop_index("ix_devices_profile_id")
        b.drop_constraint("fk_devices_profile_id_device_type_profiles", type_="foreignkey")
        b.drop_column("profile_id")
    op.drop_table("device_type_profiles")
