"""Connections v1 (design/reports.md): a strict subset of DB item 11 / DEVICE_DATA_MODEL §7.

Built (item 32): device_ports (incl. nullable lanes/rear_port_id/rear_position), cables (no status),
connections (lanes always 0, non-partial uniques, no status). Not built: connection_hops, breakout lanes > 0,
connection/cable status, cable external_id/trail/mode/project_id, port_ip_config.
"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Index, Numeric, Text, text
from sqlmodel import Field

from app.enums import CableType, sql_in
from app.timestamps import TimestampMixin, ts_field

PORT_KINDS = ("ethernet", "fiber", "console", "mgmt", "power", "tap", "patch", "other")
PORT_ROLES = ("endpoint", "front", "rear")
LIVE_PORT = "deleted_at IS NULL"


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
    """v1 (item 32): no status; one cable per connection, deleted with it."""
    __tablename__ = "cables"
    __table_args__ = (
        CheckConstraint(f"cable_type IS NULL OR {sql_in('cable_type', CableType)}", name="cable_type"),
        CheckConstraint("length_m IS NULL OR length_m > 0", name="length_m"),
        Index("uq_cables_label", text("lower(label)"), unique=True,
              sqlite_where=text("label IS NOT NULL"), postgresql_where=text("label IS NOT NULL")),
    )

    id: int | None = Field(default=None, primary_key=True)
    label: str | None = Field(default=None, max_length=64)
    cable_type: str | None = Field(default=None, max_length=16)
    color: str | None = Field(default=None, max_length=32)
    length_m: Decimal | None = Field(default=None, sa_type=Numeric(8, 2))


# One row = one live connection (v1 has no status: DELETE removes the row)
class ConnectionRow(TimestampMixin, table=True):
    __tablename__ = "connections"
    __table_args__ = (
        CheckConstraint("port1_id <> port2_id", name="no_self"),
        CheckConstraint("port1_id < port2_id", name="ordered"),
        CheckConstraint("port1_lane >= 0", name="port1_lane"),
        CheckConstraint("port2_lane >= 0", name="port2_lane"),
        Index("uq_connections_port1_lane_active", "port1_id", "port1_lane", unique=True),
        Index("uq_connections_port2_lane_active", "port2_id", "port2_lane", unique=True),
    )

    id: int | None = Field(default=None, primary_key=True)
    cable_id: int | None = Field(default=None, foreign_key="cables.id", ondelete="SET NULL", index=True)
    port1_id: int = Field(foreign_key="device_ports.id", ondelete="RESTRICT", index=True)
    port1_lane: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    port2_id: int = Field(foreign_key="device_ports.id", ondelete="RESTRICT", index=True)
    port2_lane: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    notes: str | None = Field(default=None, sa_type=Text)
