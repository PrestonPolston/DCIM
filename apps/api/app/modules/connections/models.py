"""Connections v1 (design/reports.md): a strict subset of DB item 11 / DEVICE_DATA_MODEL §7.

Built (item 32): device_ports (incl. nullable lanes/rear_port_id/rear_position), cables, connections.
p1_34_cable_matrix_rest (job intake slice 3) adds: cable/connection status + removed_at, cables.external_id/trail/
cable_mode/project_id, connections.action/change_set_id, connection_hops and port_ip_config. The (port, lane) and
label uniques are partial on status <> 'removed'. The manual /connections API still writes active rows only.
"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Index, Numeric, Text, text, true
from sqlmodel import Field

from app.enums import CableType, sql_in
from app.timestamps import TimestampMixin, ts_field

PORT_KINDS = ("ethernet", "fiber", "console", "mgmt", "power", "tap", "patch", "other")
PORT_ROLES = ("endpoint", "front", "rear")
LIVE_PORT = "deleted_at IS NULL"
LINK_STATUSES = ("planned", "active", "removed")
CONNECTION_ACTIONS = ("add", "remove", "move")
CABLE_MODES = ("smf", "mmf", "copper", "dac", "aoc", "mpo")
NOT_REMOVED = "status <> 'removed'"


def _in(col, values):
    return f"{col} IN (" + ",".join(f"'{v}'" for v in values) + ")"


class DevicePortRow(TimestampMixin, table=True):
    __tablename__ = "device_ports"
    __table_args__ = (
        CheckConstraint(f"kind IS NULL OR {_in('kind', PORT_KINDS)}", name="kind"),
        CheckConstraint(_in("role", PORT_ROLES), name="role"),
        CheckConstraint("lanes IS NULL OR (lanes >= 1 AND lanes <= 32)", name="lanes"),
        CheckConstraint("speed_mbps IS NULL OR speed_mbps > 0", name="speed_mbps"),
        CheckConstraint("face IS NULL OR face IN ('front','rear')", name="face"),
        CheckConstraint("(role = 'front') = (rear_port_id IS NOT NULL AND rear_position IS NOT NULL)",
                        name="front_map"),
        CheckConstraint("rear_port_id IS NULL OR rear_port_id <> id", name="not_self"),
        CheckConstraint("rear_position IS NULL OR rear_position >= 1", name="rear_position"),
        Index("uq_device_ports_rear_position", "rear_port_id", "rear_position", unique=True,
              sqlite_where=text("rear_port_id IS NOT NULL"), postgresql_where=text("rear_port_id IS NOT NULL")),
        Index("uq_device_ports_device_slot_name", "device_id", text("coalesce(slot, '')"), text("lower(name)"),
              unique=True, sqlite_where=text(LIVE_PORT), postgresql_where=text(LIVE_PORT)),
    )

    id: int | None = Field(default=None, primary_key=True)
    device_id: int = Field(foreign_key="devices.id", ondelete="CASCADE", index=True)
    slot: str | None = Field(default=None, max_length=64)
    name: str = Field(max_length=64)
    kind: str | None = Field(default=None, max_length=16)
    role: str = Field(default="endpoint", max_length=8, sa_column_kwargs={"server_default": "endpoint"})
    lanes: int | None = None
    rear_port_id: int | None = Field(default=None, foreign_key="device_ports.id", ondelete="RESTRICT", index=True)
    rear_position: int | None = None
    connector: str | None = Field(default=None, max_length=32)
    speed_mbps: int | None = None
    transceiver_make: str | None = Field(default=None, max_length=64)
    transceiver_model: str | None = Field(default=None, max_length=64)
    face: str | None = Field(default=None, max_length=8)
    deleted_at: datetime | None = ts_field()


class CableRow(TimestampMixin, table=True):
    """One physical cable. The manual API keeps one cable per connection; the cable-matrix import sets trail,
    external_id (the matrix ID) and project_id (the job)."""
    __tablename__ = "cables"
    __table_args__ = (
        CheckConstraint(f"cable_type IS NULL OR {sql_in('cable_type', CableType)}", name="cable_type"),
        CheckConstraint("length_m IS NULL OR length_m > 0", name="length_m"),
        CheckConstraint(f"cable_mode IS NULL OR {_in('cable_mode', CABLE_MODES)}", name="cable_mode"),
        CheckConstraint(_in("status", LINK_STATUSES), name="status"),
        CheckConstraint("(status = 'removed') = (removed_at IS NOT NULL)", name="removed"),
        Index("uq_cables_label", text("lower(label)"), unique=True,
              sqlite_where=text("label IS NOT NULL AND status <> 'removed'"),
              postgresql_where=text("label IS NOT NULL AND status <> 'removed'")),
        Index("uq_cables_external_id", "external_id", unique=True,
              sqlite_where=text("external_id IS NOT NULL"), postgresql_where=text("external_id IS NOT NULL")),
    )

    id: int | None = Field(default=None, primary_key=True)
    label: str | None = Field(default=None, max_length=64)
    cable_type: str | None = Field(default=None, max_length=16)
    color: str | None = Field(default=None, max_length=32)
    length_m: Decimal | None = Field(default=None, sa_type=Numeric(8, 2))
    external_id: str | None = Field(default=None, max_length=64)
    trail: str | None = Field(default=None, max_length=128, index=True)
    cable_mode: str | None = Field(default=None, max_length=8)
    status: str = Field(default="active", max_length=8, sa_column_kwargs={"server_default": "active"})
    removed_at: datetime | None = ts_field()
    project_id: int | None = Field(default=None, foreign_key="projects.id", ondelete="SET NULL", index=True)


# One row = one connection between two endpoint ports. (port, lane) is unique among non-removed rows.
class ConnectionRow(TimestampMixin, table=True):
    __tablename__ = "connections"
    __table_args__ = (
        CheckConstraint("port1_id <> port2_id", name="no_self"),
        CheckConstraint("port1_id < port2_id", name="ordered"),
        CheckConstraint("port1_lane >= 0", name="port1_lane"),
        CheckConstraint("port2_lane >= 0", name="port2_lane"),
        CheckConstraint(_in("status", LINK_STATUSES), name="status"),
        CheckConstraint(f"action IS NULL OR {_in('action', CONNECTION_ACTIONS)}", name="action"),
        CheckConstraint("(status = 'removed') = (removed_at IS NOT NULL)", name="removed"),
        Index("uq_connections_port1_lane_active", "port1_id", "port1_lane", unique=True,
              sqlite_where=text(NOT_REMOVED), postgresql_where=text(NOT_REMOVED)),
        Index("uq_connections_port2_lane_active", "port2_id", "port2_lane", unique=True,
              sqlite_where=text(NOT_REMOVED), postgresql_where=text(NOT_REMOVED)),
    )

    id: int | None = Field(default=None, primary_key=True)
    cable_id: int | None = Field(default=None, foreign_key="cables.id", ondelete="SET NULL", index=True)
    port1_id: int = Field(foreign_key="device_ports.id", ondelete="RESTRICT", index=True)
    port1_lane: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    port2_id: int = Field(foreign_key="device_ports.id", ondelete="RESTRICT", index=True)
    port2_lane: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    notes: str | None = Field(default=None, sa_type=Text)
    status: str = Field(default="active", max_length=8, sa_column_kwargs={"server_default": "active"})
    action: str | None = Field(default=None, max_length=8)
    removed_at: datetime | None = ts_field()
    change_set_id: int | None = Field(default=None, foreign_key="change_sets.id", ondelete="SET NULL", index=True)


class ConnectionHopRow(TimestampMixin, table=True):
    """Ordered panel ports a connection passes through (DEVICE_DATA_MODEL §7). A rear MPO port carries lane =
    MPO position; a front port or plain trunk uses lane 0. One active hop per (port, lane)."""
    __tablename__ = "connection_hops"
    __table_args__ = (
        CheckConstraint("seq >= 1 AND seq <= 32", name="seq"),
        CheckConstraint("lane >= 0", name="lane"),
        Index("uq_connection_hops_connection_id_seq", "connection_id", "seq", unique=True),
        Index("uq_connection_hops_port_lane_active", "port_id", "lane", unique=True,
              sqlite_where=text("is_active"), postgresql_where=text("is_active")),
    )

    id: int | None = Field(default=None, primary_key=True)
    connection_id: int = Field(foreign_key="connections.id", ondelete="CASCADE")
    seq: int
    port_id: int = Field(foreign_key="device_ports.id", ondelete="RESTRICT", index=True)
    lane: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    cable_id: int | None = Field(default=None, foreign_key="cables.id", ondelete="SET NULL", index=True)
    label: str | None = Field(default=None, max_length=128)
    is_active: bool = Field(default=True, sa_column_kwargs={"server_default": true()})


class PortIpConfigRow(TimestampMixin, table=True):
    """Network / VLAN / IP on a port (cable matrix Z side). No secrets; several rows per port allowed."""
    __tablename__ = "port_ip_config"
    __table_args__ = (
        CheckConstraint("vlan IS NULL OR (vlan >= 1 AND vlan <= 4094)", name="vlan"),
        CheckConstraint("native_vlan IS NULL OR (native_vlan >= 1 AND native_vlan <= 4094)", name="native_vlan"),
        CheckConstraint("prefix_len IS NULL OR (prefix_len >= 0 AND prefix_len <= 128)", name="prefix_len"),
    )

    id: int | None = Field(default=None, primary_key=True)
    port_id: int = Field(foreign_key="device_ports.id", ondelete="CASCADE", index=True)
    network: str | None = Field(default=None, max_length=64)
    vlan: int | None = None
    native_vlan: int | None = None
    ip_address: str | None = Field(default=None, max_length=45)
    prefix_len: int | None = None
    default_gateway: str | None = Field(default=None, max_length=45)
