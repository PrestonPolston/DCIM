from app.modules.images.refs import ProfileImageRef
from typing import Literal

from pydantic import BaseModel, Field

from app.validation import InputModel, OutputModel

from app.enums import OrientationLiteral as Orientation  # direction the front faces on the hall floor plan


# Optional floor-plan position shared by rows and racks
class FloorPosition(InputModel):
    pos_x: int | None = Field(None, ge=0, le=10_000, description="Floor grid column")
    pos_y: int | None = Field(None, ge=0, le=10_000, description="Floor grid row")
    orientation: Orientation | None = Field(None, description="Direction the front faces")


# Sites
class SiteCreate(InputModel):
    name: str = Field(min_length=1, max_length=64)
    address: str | None = Field(None, max_length=500)
    is_default: bool = Field(False, description="Make this the default site (the previous default is unset)")


class SiteUpdate(InputModel):
    name: str | None = Field(None, min_length=1, max_length=64)
    address: str | None = Field(None, max_length=500)
    is_default: bool | None = Field(
        None, description="true moves the default here; false on the default site is refused (409)"
    )


class Site(OutputModel, SiteCreate):
    model_config = OutputModel.model_config
    id: int


# Halls (belong to a site)
class HallAisle(InputModel):
    aisle_axis: Literal["x", "y"] | None = Field(
        None, description="Grid axis the center aisle runs along (y = vertical aisle). null = no hint")
    odd_side: Literal["low", "high"] | None = Field(
        None, description="Side of the aisle with odd-numbered rows (low = smaller coordinate). null = no hint")


class HallCreate(HallAisle):
    site_id: int | None = Field(None, description="Alias building_id. Omitted = the default site")
    name: str = Field(min_length=1, max_length=64)


class HallUpdate(HallAisle):
    name: str | None = Field(None, min_length=1, max_length=64)


class Hall(OutputModel, HallCreate):
    model_config = OutputModel.model_config
    id: int
    site_id: int


# Rows (belong to a hall)
class RowCreate(FloorPosition):
    hall_id: int = Field(description="Alias room_id")
    name: str = Field(min_length=1, max_length=64)


class RowUpdate(FloorPosition):
    name: str | None = Field(None, min_length=1, max_length=64)


class Row(OutputModel, RowCreate):
    model_config = OutputModel.model_config
    id: int


# Racks (belong to a row)
class RackCreate(FloorPosition):
    row_id: int
    name: str = Field(min_length=1, max_length=64)
    u_height: int = Field(53, ge=1, le=100)


class RackUpdate(FloorPosition):
    name: str | None = Field(None, min_length=1, max_length=64)
    u_height: int | None = Field(None, ge=1, le=100)


class Rack(OutputModel, RackCreate):
    model_config = OutputModel.model_config
    id: int
    hall_id: int | None = Field(None, description="The row's hall (denormalized, read-only; P1-10)")
    effective_orientation: Orientation | None = Field(
        None, description="orientation, or the row's orientation when the rack's own is null"
    )


# Hall floor plan: GET /halls/{id}/layout
class RackLayout(Rack):
    device_count: int
    u_used: int  # sum of device U heights (front+rear half-depth both count)
    u_free: int


class RowLayout(Row):
    racks: list[RackLayout]


class HallLayout(Hall):
    rows: list[RowLayout]


# Rack elevation: GET /racks/{id}/elevation
class ElevationDeviceType(BaseModel):
    id: int
    manufacturer: str
    name: str
    u_height: int
    is_full_depth: bool


class ElevationDevice(BaseModel):
    id: int
    host_name: str
    status: str
    serial_number: str | None
    position_u: int  # lowest U occupied
    top_u: int  # highest U occupied
    face: str
    profile_id: int | None = None
    serial_unavailable: bool = False
    serial_note: str | None = None
    needs_review: bool = False
    needs_review_reason: str | None = None
    effective_front_image: ProfileImageRef | None = None
    effective_rear_image: ProfileImageRef | None = None
    # From the device's profile (3D row view). face says which side a half-depth device sits on: front or rear
    is_full_depth: bool = Field(True, description="Profile is_full_depth; full-depth devices block both faces")
    mounting: str | None = Field(None, description="Profile mounting (rack_19in, rack_23in, shelf, zero_u, other)")
    depth_mm: float | None = Field(None, description="Profile depth in mm")
    weight_kg: float | None = Field(None, description="Profile weight in kg")
    orientation: str | None = Field(None, description="Profile orientation: port_front | power_front | null")
    manufacturer: str | None = Field(None, description="Model manufacturer (device type)")
    model: str | None = Field(None, description="Model name (device type name)")
    effective_asset_type: str | None = None
    connection_count: int = 0
    device_type: ElevationDeviceType | None = Field(
        None, description="null only for a flagged placed_without_profile device (1U, both faces, until removed)")


class RackElevation(BaseModel):
    id: int
    row_id: int
    name: str
    u_height: int
    orientation: Orientation | None = None
    effective_orientation: Orientation | None = None
    u_used: int  # same rule as hall layout
    u_free: int
    devices: list[ElevationDevice]


class RowFront(BaseModel):
    id: int
    hall_id: int
    name: str
    orientation: str | None = None
    racks: list[RackElevation]
