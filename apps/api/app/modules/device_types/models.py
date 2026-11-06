from datetime import date, datetime

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, CheckConstraint, Index, Numeric, false, text, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, UniqueConstraint

from app.enums import AssetType, Airflow, Mounting, ProfileOrientation, ProfileStatus, PowerType, sql_in
from app.modules.devices.models import COLOR_CHECK
from app.timestamps import TimestampMixin


# Database table for device types, i.e. device profiles (make/model/U height)
class DeviceTypeRow(TimestampMixin, table=True):
    __tablename__ = "device_types"
    __table_args__ = (
        UniqueConstraint("manufacturer", "name"),
        CheckConstraint("u_height BETWEEN 0 AND 100", name="u_height"),
        CheckConstraint("asset_type IS NULL OR " + sql_in("asset_type", AssetType), name="asset_type"),
    )

    id: int | None = Field(default=None, primary_key=True)
    manufacturer: str = Field(index=True)
    name: str = Field(index=True)  # model name, e.g. "PowerEdge R650"
    u_height: int = Field(default=1, sa_column_kwargs={"server_default": "1"})
    # full-depth gear blocks both rack faces
    is_full_depth: bool = Field(default=True, sa_column_kwargs={"server_default": true()})
    asset_type: str | None = Field(default=None, max_length=32)  # default for its devices
    eos_date: date | None = None  # default end of support for its devices


JSONType = JSON().with_variant(JSONB, "postgresql")


# Device profile: physical/rendering data for a device type (one default per type)
class DeviceTypeProfileRow(TimestampMixin, table=True):
    __tablename__ = "device_type_profiles"
    __table_args__ = (
        UniqueConstraint("device_type_id", "name"),
        Index(
            "uq_device_type_profiles_default", "device_type_id", unique=True,
            sqlite_where=text("is_default"), postgresql_where=text("is_default"),
        ),
        CheckConstraint("u_height BETWEEN 0 AND 100", name="u_height"),
        CheckConstraint(
            "(width_mm IS NULL OR width_mm > 0) AND (height_mm IS NULL OR height_mm > 0) "
            "AND (depth_mm IS NULL OR depth_mm > 0)",
            name="dims",
        ),
        CheckConstraint(COLOR_CHECK.format(col="color_hex"), name="color_hex"),
        CheckConstraint("airflow IS NULL OR " + sql_in("airflow", Airflow), name="airflow"),
        CheckConstraint("orientation IS NULL OR " + sql_in("orientation", ProfileOrientation), name="orientation"),
        CheckConstraint("power_type IS NULL OR " + sql_in("power_type", PowerType), name="power_type"),
        CheckConstraint(sql_in("status", ProfileStatus), name="status"),
        CheckConstraint("mounting IS NULL OR " + sql_in("mounting", Mounting), name="mounting"),
        CheckConstraint("weight_kg IS NULL OR (weight_kg > 0 AND weight_kg <= 2000)", name="weight_kg"),
        CheckConstraint("status <> 'published' OR published_at IS NOT NULL", name="published_at"),
        Index("ix_device_type_profiles_status", "status"),
        CheckConstraint("version >= 1", name="version"),
    )

    id: int | None = Field(default=None, primary_key=True)
    device_type_id: int = Field(foreign_key="device_types.id", ondelete="CASCADE", index=True)
    name: str
    is_default: bool = Field(default=False, sa_column_kwargs={"server_default": false()})
    u_height: int
    width_mm: float | None = Field(default=None, sa_type=Numeric(asdecimal=False))
    height_mm: float | None = Field(default=None, sa_type=Numeric(asdecimal=False))
    depth_mm: float | None = Field(default=None, sa_type=Numeric(asdecimal=False))
    is_full_depth: bool = Field(default=True, sa_column_kwargs={"server_default": true()})
    faces: list = Field(
        default_factory=lambda: ["front", "rear"],
        sa_type=JSONType,
        nullable=False,
        sa_column_kwargs={"server_default": text("'[\"front\",\"rear\"]'")},
    )
    ports: list | dict | None = Field(default=None, sa_type=JSONType)
    power: list | dict | None = Field(default=None, sa_type=JSONType)
    model_refs: list | dict | None = Field(default=None, sa_type=JSONType)
    color_hex: str | None = Field(default=None, max_length=7)  # default device color (#RRGGBB)
    airflow: str | None = Field(default=None, max_length=16)
    orientation: str | None = Field(default=None, max_length=16)  # p1_21 (D58): port_front | power_front
    power_type: str | None = Field(default=None, max_length=8)  # AC / DC / AC_DC
    # p1_17 lifecycle: draft -> published -> retired. Only published profiles may be used by devices.
    status: str = Field(default="draft", max_length=16, sa_column_kwargs={"server_default": "draft"})
    mounting: str | None = Field(default=None, max_length=16)
    weight_kg: float | None = Field(default=None, sa_type=Numeric(asdecimal=False))
    published_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    retired_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    published_by: str | None = Field(default=None, max_length=128)
    version: int = Field(default=1, sa_column_kwargs={"server_default": "1"})
    supersedes_profile_id: int | None = Field(default=None, sa_column=Column(
        Integer, ForeignKey("device_type_profiles.id", name="fk_device_type_profiles_supersedes", ondelete="RESTRICT"),
        index=True))
