from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Text, func, text
from sqlmodel import Field, SQLModel

from app.enums import DeviceStatus, sql_in
from app.timestamps import utcnow

CHANGE_SOURCES = ("api", "csv_import", "migration", "script")


def _at(**kw):
    return Field(
        default_factory=utcnow, nullable=False, sa_type=DateTime(timezone=True),
        sa_column_kwargs={"server_default": func.now()}, **kw,
    )


# Groups the history rows written by one API request or one CSV import
class ChangeSetRow(SQLModel, table=True):
    __tablename__ = "change_sets"
    __table_args__ = (
        CheckConstraint("source IN ('api','csv_import','migration','script')", name="source"),
        CheckConstraint("export_sha256 IS NULL OR length(export_sha256) = 64", name="export_sha256"),
    )

    id: int | None = Field(default=None, primary_key=True)
    source: str
    actor: str | None = None
    note: str | None = Field(default=None, sa_type=Text)
    created_at: datetime | None = _at()
    export_path: str | None = Field(default=None, sa_type=Text)  # p1_19 (D47): removal export file
    export_sha256: str | None = Field(default=None, max_length=64)


# p1_19 (D46): which removed device was restored by which change set; the PK refuses a second restore
class RestoredDeviceRow(SQLModel, table=True):
    __tablename__ = "restored_devices"

    source_change_set_id: int = Field(foreign_key="change_sets.id", ondelete="RESTRICT", primary_key=True)
    original_device_id: int = Field(primary_key=True)
    restored_device_id: int | None = Field(default=None, foreign_key="devices.id", ondelete="SET NULL")
    restore_change_set_id: int = Field(foreign_key="change_sets.id", ondelete="RESTRICT", index=True)
    restored_at: datetime | None = _at()


class DeviceStatusHistoryRow(SQLModel, table=True):
    __tablename__ = "device_status_history"
    __table_args__ = (
        CheckConstraint(sql_in("to_status", DeviceStatus), name="to_status"),
        Index("ix_device_status_history_device_id_changed_at", "device_id", "changed_at"),
        Index("ix_device_status_history_to_status_changed_at", "to_status", "changed_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    device_id: int = Field(foreign_key="devices.id", ondelete="RESTRICT")
    from_status: str | None = None
    to_status: str
    changed_at: datetime | None = _at()
    changed_by: str | None = None
    reason: str | None = None
    change_set_id: int | None = Field(default=None, foreign_key="change_sets.id", ondelete="RESTRICT")


class DevicePlacementHistoryRow(SQLModel, table=True):
    __tablename__ = "device_placement_history"
    __table_args__ = (
        Index("ix_device_placement_history_device_id_changed_at", "device_id", "changed_at"),
        Index("ix_device_placement_history_to_rack_id_changed_at", "to_rack_id", "changed_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    device_id: int = Field(foreign_key="devices.id", ondelete="RESTRICT")
    from_rack_id: int | None = Field(default=None, foreign_key="racks.id", ondelete="RESTRICT")
    from_position_u: int | None = None
    from_face: str | None = None
    to_rack_id: int | None = Field(default=None, foreign_key="racks.id", ondelete="RESTRICT")
    to_position_u: int | None = None
    to_face: str | None = None
    reason: str | None = None
    changed_at: datetime | None = _at()
    changed_by: str | None = None
    change_set_id: int | None = Field(default=None, foreign_key="change_sets.id", ondelete="RESTRICT")


# Previous host names (P1-7): one row per rename, same change_set as the rename
class DeviceNameHistoryRow(SQLModel, table=True):
    __tablename__ = "device_name_history"
    __table_args__ = (
        Index("ix_device_name_history_device_id_changed_at", "device_id", "changed_at"),
        Index("ix_device_name_history_old_name_lower", text("lower(old_name)")),
    )

    id: int | None = Field(default=None, primary_key=True)
    device_id: int = Field(foreign_key="devices.id", ondelete="RESTRICT")
    old_name: str = Field(max_length=253)
    new_name: str = Field(max_length=253)
    changed_at: datetime | None = _at()
    changed_by: str | None = None
    change_set_id: int | None = Field(default=None, foreign_key="change_sets.id", ondelete="RESTRICT")
