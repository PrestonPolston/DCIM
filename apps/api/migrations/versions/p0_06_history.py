"""P0-06: change_sets + device status/placement history; decom'd devices unracked

Revision ID: p0_06_history
Revises: p0_05_profiles
"""
import sqlalchemy as sa
from alembic import op

from migrations.p0_common import NC

revision = "p0_06_history"
down_revision = "p0_05_profiles"
branch_labels = None
depends_on = None


def _at(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable, server_default=sa.func.now())


def _cs_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["change_set_id"], ["change_sets.id"], ondelete="RESTRICT", name=f"fk_{table}_change_set_id_change_sets"
    )


def upgrade() -> None:
    op.create_table(
        "change_sets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("actor", sa.String(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        _at("created_at"),
        sa.PrimaryKeyConstraint("id", name="pk_change_sets"),
        sa.CheckConstraint("source IN ('api','csv_import','migration','script')", name="ck_change_sets_source"),
    )
    op.create_table(
        "device_status_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("from_status", sa.String(), nullable=True),
        sa.Column("to_status", sa.String(), nullable=False),
        _at("changed_at"),
        sa.Column("changed_by", sa.String(), nullable=True),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("change_set_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_device_status_history"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="RESTRICT",
                                name="fk_device_status_history_device_id_devices"),
        _cs_fk("device_status_history"),
        sa.CheckConstraint("to_status IN ('install','active','decom')", name="ck_device_status_history_to_status"),
    )
    op.create_index("ix_device_status_history_device_id_changed_at", "device_status_history", ["device_id", "changed_at"])
    op.create_index("ix_device_status_history_to_status_changed_at", "device_status_history", ["to_status", "changed_at"])
    op.create_table(
        "device_placement_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("from_rack_id", sa.Integer(), nullable=True),
        sa.Column("from_position_u", sa.Integer(), nullable=True),
        sa.Column("from_face", sa.String(), nullable=True),
        sa.Column("to_rack_id", sa.Integer(), nullable=True),
        sa.Column("to_position_u", sa.Integer(), nullable=True),
        sa.Column("to_face", sa.String(), nullable=True),
        sa.Column("reason", sa.String(), nullable=True),
        _at("changed_at"),
        sa.Column("changed_by", sa.String(), nullable=True),
        sa.Column("change_set_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_device_placement_history"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="RESTRICT",
                                name="fk_device_placement_history_device_id_devices"),
        sa.ForeignKeyConstraint(["from_rack_id"], ["racks.id"], ondelete="RESTRICT",
                                name="fk_device_placement_history_from_rack_id_racks"),
        sa.ForeignKeyConstraint(["to_rack_id"], ["racks.id"], ondelete="RESTRICT",
                                name="fk_device_placement_history_to_rack_id_racks"),
        _cs_fk("device_placement_history"),
    )
    op.create_index("ix_device_placement_history_device_id_changed_at", "device_placement_history", ["device_id", "changed_at"])
    op.create_index("ix_device_placement_history_to_rack_id_changed_at", "device_placement_history", ["to_rack_id", "changed_at"])

    # Data step: decom'd devices that still hold a rack position get unracked (with history)
    bind = op.get_bind()
    racked_decom = bind.execute(sa.text(
        "SELECT id, rack_id, position_u, face FROM devices WHERE status = 'decom' AND rack_id IS NOT NULL"
    )).fetchall()
    if racked_decom:
        cs_id = bind.execute(sa.text(
            "INSERT INTO change_sets (source, note) VALUES ('migration', 'p0_06: unrack decommissioned devices') "
            "RETURNING id"
        )).scalar()
        for dev_id, rack_id, pos, face in racked_decom:
            bind.execute(sa.text(
                "INSERT INTO device_placement_history (device_id, from_rack_id, from_position_u, from_face, "
                "reason, change_set_id) VALUES (:d, :r, :p, :f, 'decom auto-unrack (migration)', :cs)"
            ), {"d": dev_id, "r": rack_id, "p": pos, "f": face, "cs": cs_id})
        op.execute(
            "UPDATE devices SET rack_id = NULL, position_u = NULL, face = 'front' "
            "WHERE status = 'decom' AND rack_id IS NOT NULL"
        )
    with op.batch_alter_table("devices", recreate="auto", naming_convention=NC) as b:
        b.create_check_constraint("decom_unracked", "status <> 'decom' OR rack_id IS NULL")


def downgrade() -> None:
    with op.batch_alter_table("devices", recreate="auto", naming_convention=NC) as b:
        b.drop_constraint(op.f("ck_devices_decom_unracked"), type_="check")
    op.drop_table("device_placement_history")
    op.drop_table("device_status_history")
    op.drop_table("change_sets")
