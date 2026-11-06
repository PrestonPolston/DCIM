from app.modules.images.refs import ProfileImageRef
from app.enums import AssetTypeLiteral
from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

from app.validation import InputModel, OutputModel

from app.enums import DeviceStatusLiteral as Status
from app.enums import ConfidenceLiteral as Confidence
from app.enums import FaceLiteral as Face

COLOR = r"^#[0-9A-Fa-f]{6}$"


# Optional descriptive fields (P1-2); shared by create and update
class DeviceDescriptive(InputModel):
    description: str | None = Field(None, max_length=10_000)
    notes: str | None = Field(None, max_length=10_000)
    asset_type: AssetTypeLiteral | None = Field(None, description="null = the device type's asset_type")
    eos_date: date | None = Field(None, description="End of support; null = the device type's eos_date")
    app_service: str | None = Field(None, max_length=128)
    system_type: str | None = Field(None, max_length=64)
    system_type_confidence: Confidence | None = None
    color_hex: str | None = Field(None, pattern=COLOR, description="#RRGGBB; null = profile color")
    power_assignment: str | None = Field(None, max_length=2000, description="Free text for now")
    historic_name: str | None = Field(None, max_length=255, description="Legacy previous name")
    owner: str | None = Field(None, max_length=255, description="Free text; blank = null")
    project_id: int | None = Field(None, description="Current project")

    @field_validator("owner", mode="before")
    @classmethod
    def _blank_owner(cls, v):
        return None if isinstance(v, str) and not v.strip() else v


# Data the client sends to create a device
class DeviceCreate(DeviceDescriptive):
    host_name: str = Field(min_length=1, max_length=253)
    rack: str | None = Field(None, max_length=64, description="Legacy free-text rack label")
    status: Status = Field("install", description="Default install (changed from active)")
    device_type_id: int | None = None
    rack_id: int | None = None
    position_u: int | None = Field(None, ge=1, description="Lowest U occupied (1-based)")
    profile_id: int | None = Field(None, description="Profile override; null = type default")
    face: Face = "front"
    serial_number: str | None = Field(
        None, min_length=1, max_length=64, description="Vendor serial or asset tag; unique when set"
    )
    serial_unavailable: bool = Field(False, description="Serial not accessible; requires serial_number null")
    serial_note: str | None = Field(None, max_length=128)


# Drag-to-rack placement (POST /racks/{rack_id}/devices): same rules as POST /devices, rack from the path
class RackDeviceCreate(DeviceDescriptive):
    host_name: str = Field(min_length=1, max_length=253)
    profile_id: int = Field(description="A published profile (the dragged catalog item)")
    position_u: int = Field(ge=1, description="Lowest U occupied (1-based)")
    face: Face = "front"
    status: Status = "install"
    serial_number: str | None = Field(None, min_length=1, max_length=64)
    serial_unavailable: bool = False
    serial_note: str | None = Field(None, max_length=128)


# Data the API returns (adds the server-assigned id)
class Device(OutputModel, DeviceCreate):
    model_config = OutputModel.model_config
    id: int
    created_by: str | None = None
    needs_review: bool = False  # read-only (item 49)
    needs_review_reason: str | None = None  # placed_without_profile | profile_not_published | other
    effective_asset_type: AssetTypeLiteral | None = None
    effective_eos_date: date | None = None
    effective_color_hex: str | None = None
    effective_front_image: ProfileImageRef | None = Field(None, description="The profile's front image")
    effective_rear_image: ProfileImageRef | None = Field(None, description="The profile's rear image")
    orientation: str | None = Field(None, description="From the profile: port_front | power_front | null (read-only)")


# Data the client sends to change a device (any subset of fields)
class DeviceUpdate(DeviceDescriptive):
    host_name: str | None = Field(None, min_length=1, max_length=253)
    rack: str | None = Field(None, max_length=64)
    status: Status | None = None
    device_type_id: int | None = None
    rack_id: int | None = None
    position_u: int | None = Field(None, ge=1)
    profile_id: int | None = None
    recommission: bool = Field(False, description="Allow leaving decom (back to install/active)")
    face: Face | None = None
    serial_number: str | None = Field(None, min_length=1, max_length=64)
    serial_unavailable: bool | None = None
    serial_note: str | None = Field(None, max_length=128)


# One CSV row that failed validation (row 2 = first data row after the header)
class ImportRowError(BaseModel):
    row: int
    errors: list[str]  # messages (kept for existing clients)
    details: list[dict] = Field(default_factory=list,
                                description="Same errors as {code, message, ...} (e.g. profile_required with profile_id)")


# Result of a CSV import; nothing is saved when dry_run is true or errors exist
class ImportResult(BaseModel):
    dry_run: bool
    total_rows: int
    created: int
    errors: list[ImportRowError]
    errors_truncated: bool = False
    warnings: list[str] = []


class NameHistory(BaseModel):
    id: int
    device_id: int
    old_name: str
    new_name: str
    changed_at: datetime
    changed_by: str | None = None
    change_set_id: int | None = None
