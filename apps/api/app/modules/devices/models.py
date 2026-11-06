from datetime import date, datetime

from sqlalchemy import CheckConstraint, Index, Text, false, text
from sqlmodel import Field

from app.enums import AssetType, Confidence, DeviceStatus, Face, sql_in
from app.timestamps import SoftDeleteMixin, TimestampMixin, ts_field

HOSTNAME_SCOPE = "rack_id IS NOT NULL AND deleted_at IS NULL"
# null-tolerant '#RRGGBB' (format is fully validated by the API)
COLOR_CHECK = "{col} IS NULL OR (length({col}) = 7 AND substr({col}, 1, 1) = '#')"


# Database table for devices
class DeviceRow(TimestampMixin, SoftDeleteMixin, table=True):
    __tablename__ = "devices"
    __table_args__ = (
        CheckConstraint(sql_in("status", DeviceStatus), name="status"),
        CheckConstraint(sql_in("face", Face), name="face"),
        CheckConstraint("position_u IS NULL OR position_u >= 1", name="position_u"),
        CheckConstraint(
            "(rack_id IS NULL AND position_u IS NULL) OR (rack_id IS NOT NULL AND position_u IS NOT NULL)",
            name="placement",
        ),
        CheckConstraint(
            "serial_number IS NULL OR length(trim(serial_number)) > 0", name="serial_nonempty"
        ),
        CheckConstraint("length(trim(host_name)) > 0", name="host_name_nonempty"),
        # decommissioned devices never hold a rack position
        CheckConstraint("status <> 'decom' OR rack_id IS NULL", name="decom_unracked"),
        CheckConstraint("system_type_confidence IS NULL OR " + sql_in("system_type_confidence", Confidence),
                        name="system_type_confidence"),
        CheckConstraint(COLOR_CHECK.format(col="color_hex"), name="color_hex"),
        CheckConstraint("owner IS NULL OR length(trim(owner)) > 0", name="owner_nonempty"),
        Index("ix_devices_owner_lower", text("lower(owner)")),
        CheckConstraint("NOT serial_unavailable OR serial_number IS NULL", name="serial_unavailable"),
        CheckConstraint("needs_review_reason IS NULL OR needs_review_reason IN "
                        "('placed_without_profile','profile_not_published','other')", name="needs_review_reason"),
        CheckConstraint("needs_review = (needs_review_reason IS NOT NULL)", name="needs_review"),
        CheckConstraint("asset_type IS NULL OR " + sql_in("asset_type", AssetType), name="asset_type"),
        Index("ix_devices_needs_review", "needs_review",
              sqlite_where=text("needs_review"), postgresql_where=text("needs_review")),
        # D1: host names are unique per rack (cabinet), case-insensitive, live racked devices only
        Index(
            "uq_devices_rack_id_host_name", "rack_id", text("lower(host_name)"), unique=True,
            sqlite_where=text(HOSTNAME_SCOPE), postgresql_where=text(HOSTNAME_SCOPE),
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    host_name: str = Field(index=True)
    rack: str | None = None  # legacy free-text rack label (use rack_id for placement)
    status: str = Field(default="install", index=True, sa_column_kwargs={"server_default": "install"})
    device_type_id: int | None = Field(
        default=None, foreign_key="device_types.id", ondelete="RESTRICT", index=True
    )
    rack_id: int | None = Field(default=None, foreign_key="racks.id", ondelete="RESTRICT", index=True)
    # p1_18: every device has a (published, when created) profile; resolved from the type default if not given
    profile_id: int | None = Field(
        default=None, foreign_key="device_type_profiles.id", ondelete="RESTRICT", index=True, nullable=False
    )
    position_u: int | None = None  # lowest U the device occupies (1-based)
    face: str = Field(default="front", sa_column_kwargs={"server_default": "front"})
    serial_number: str | None = Field(default=None, unique=True)  # vendor serial or asset tag
    serial_unavailable: bool = Field(default=False, sa_column_kwargs={"server_default": false()})
    serial_note: str | None = Field(default=None, max_length=128)  # e.g. "behind PSU"
    # item 49: set by migrations/scripts only (read-only in API/CSV)
    needs_review: bool = Field(default=False, sa_column_kwargs={"server_default": false()})
    needs_review_reason: str | None = Field(default=None, max_length=32)
    # lifecycle timestamps (UTC)
    status_changed_at: datetime | None = ts_field()
    installed_at: datetime | None = ts_field()
    activated_at: datetime | None = ts_field()
    decommissioned_at: datetime | None = ts_field()
    # descriptive fields (P1-2); all optional, only host_name is required
    description: str | None = Field(default=None, sa_type=Text)
    notes: str | None = Field(default=None, sa_type=Text)
    asset_type: str | None = Field(default=None, max_length=32)  # null = device type's asset_type
    eos_date: date | None = None  # end of support; null = device type's eos_date
    created_by: str | None = Field(default=None, max_length=128)  # set from the actor
    app_service: str | None = Field(default=None, max_length=128)
    system_type: str | None = Field(default=None, max_length=64)
    system_type_confidence: str | None = Field(default=None, max_length=16)
    color_hex: str | None = Field(default=None, max_length=7)  # null = profile color
    power_assignment: str | None = Field(default=None, sa_type=Text)  # free text for now
    historic_name: str | None = Field(default=None, max_length=255)  # legacy import value
    owner: str | None = Field(default=None, max_length=255)  # free text (D13), separate from managed-by
    project_id: int | None = Field(default=None, foreign_key="projects.id", ondelete="SET NULL", index=True)
