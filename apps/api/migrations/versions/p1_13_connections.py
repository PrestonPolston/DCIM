"""Connections v1: device_ports, cables, connections (item 32: strict subset of item 11;
lanes/panel columns present but unused, non-partial port uniques, no status, no hops)

Revision ID: p1_13_connections
Revises: p1_12_rack_default_53
"""
import sqlalchemy as sa
from alembic import op

revision = "p1_13_connections"
down_revision = "p1_12_rack_default_53"
branch_labels = None
depends_on = None


def _ts():
    return [sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())]


def _where(cond):
    return {"sqlite_where": sa.text(cond), "postgresql_where": sa.text(cond)}


def upgrade() -> None:
    op.create_table(
        "device_ports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("slot", sa.String(64)),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(16)),
        sa.Column("role", sa.String(8), nullable=False, server_default="endpoint"),
        sa.Column("lanes", sa.Integer()),
        sa.Column("rear_port_id", sa.Integer()),
        sa.Column("rear_position", sa.Integer()),
        sa.Column("connector", sa.String(32)),
        sa.Column("speed_mbps", sa.Integer()),
        sa.Column("transceiver_make", sa.String(64)),
        sa.Column("transceiver_model", sa.String(64)),
        sa.Column("face", sa.String(8)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        *_ts(),
        sa.PrimaryKeyConstraint("id", name="pk_device_ports"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], name="fk_device_ports_device_id_devices",
                                ondelete="CASCADE"),
        sa.CheckConstraint("kind IS NULL OR kind IN ('ethernet','fiber','console','mgmt','power','tap','patch','other')",
                           name="ck_device_ports_kind"),
        sa.CheckConstraint("role IN ('endpoint','front','rear')", name="ck_device_ports_role"),
        sa.CheckConstraint("lanes IS NULL OR (lanes >= 1 AND lanes <= 32)", name="ck_device_ports_lanes"),
        sa.CheckConstraint("speed_mbps IS NULL OR speed_mbps > 0", name="ck_device_ports_speed_mbps"),
        sa.CheckConstraint("face IS NULL OR face IN ('front','rear')", name="ck_device_ports_face"),
        sa.CheckConstraint("(role = 'front') = (rear_port_id IS NOT NULL AND rear_position IS NOT NULL)",
                           name="ck_device_ports_front_map"),
        sa.CheckConstraint("rear_port_id IS NULL OR rear_port_id <> id", name="ck_device_ports_not_self"),
        sa.CheckConstraint("rear_position IS NULL OR rear_position >= 1", name="ck_device_ports_rear_position"),
        sa.ForeignKeyConstraint(["rear_port_id"], ["device_ports.id"],
                                name="fk_device_ports_rear_port_id_device_ports", ondelete="RESTRICT"),
    )
    op.create_index("ix_device_ports_rear_port_id", "device_ports", ["rear_port_id"])
    op.create_index("uq_device_ports_rear_position", "device_ports", ["rear_port_id", "rear_position"], unique=True,
                    **_where("rear_port_id IS NOT NULL"))
    op.create_index("ix_device_ports_device_id", "device_ports", ["device_id"])
    op.create_index("uq_device_ports_device_slot_name", "device_ports",
                    ["device_id", sa.text("coalesce(slot, '')"), sa.text("lower(name)")], unique=True,
                    **_where("deleted_at IS NULL"))

    op.create_table(
        "cables",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(64)),
        sa.Column("cable_type", sa.String(16)),
        sa.Column("color", sa.String(32)),
        sa.Column("length_m", sa.Numeric(8, 2)),
        *_ts(),
        sa.PrimaryKeyConstraint("id", name="pk_cables"),
        sa.CheckConstraint("cable_type IS NULL OR cable_type IN ('RJ45','LC','DAC')", name="ck_cables_cable_type"),
        sa.CheckConstraint("length_m IS NULL OR length_m > 0", name="ck_cables_length_m"),
    )
    op.create_index("uq_cables_label", "cables", [sa.text("lower(label)")], unique=True,
                    **_where("label IS NOT NULL"))

    op.create_table(
        "connections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cable_id", sa.Integer()),
        sa.Column("port1_id", sa.Integer(), nullable=False),
        sa.Column("port1_lane", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("port2_id", sa.Integer(), nullable=False),
        sa.Column("port2_lane", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text()),
        *_ts(),
        sa.PrimaryKeyConstraint("id", name="pk_connections"),
        sa.ForeignKeyConstraint(["cable_id"], ["cables.id"], name="fk_connections_cable_id_cables",
                                ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["port1_id"], ["device_ports.id"], name="fk_connections_port1_id_device_ports",
                                ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["port2_id"], ["device_ports.id"], name="fk_connections_port2_id_device_ports",
                                ondelete="RESTRICT"),
        sa.CheckConstraint("port1_id <> port2_id", name="ck_connections_no_self"),
        sa.CheckConstraint("port1_id < port2_id", name="ck_connections_ordered"),
        sa.CheckConstraint("port1_lane >= 0", name="ck_connections_port1_lane"),
        sa.CheckConstraint("port2_lane >= 0", name="ck_connections_port2_lane"),
    )
    op.create_index("ix_connections_cable_id", "connections", ["cable_id"])
    op.create_index("ix_connections_port1_id", "connections", ["port1_id"])
    op.create_index("ix_connections_port2_id", "connections", ["port2_id"])
    op.create_index("uq_connections_port1_lane_active", "connections", ["port1_id", "port1_lane"], unique=True)
    op.create_index("uq_connections_port2_lane_active", "connections", ["port2_id", "port2_lane"], unique=True)


def downgrade() -> None:
    op.drop_table("connections")
    op.drop_table("cables")
    op.drop_table("device_ports")
