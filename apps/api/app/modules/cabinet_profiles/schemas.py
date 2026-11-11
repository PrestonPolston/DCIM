from datetime import datetime
from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from app.modules.images.refs import ProfileImageRef
from app.units import UnitInput, UnitLiteral, unit_field
from app.validation import InputModel, OutputModel

RackUnitWidth = Literal["19in", "23in"]
RailType = Literal["square_hole", "round_hole", "threaded"]
Door = Literal["none", "perforated", "solid", "split"]
Status = Literal["draft", "published", "retired"]
MM_FIELDS = ("width_mm", "height_mm", "depth_mm", "usable_width_mm", "usable_depth_mm",
             "rail_depth_min_mm", "rail_depth_max_mm")
DIM = dict(gt=0)  # Preston: sizes only need to be > 0 (no upper caps in the API or the DB)
COLOR = r"^#[0-9A-Fa-f]{6}$"


class _Spec(UnitInput, InputModel):
    MM_FIELDS: ClassVar[tuple[str, ...]] = MM_FIELDS
    MM_STEP: ClassVar[str] = "1"
    unit: UnitLiteral | None = unit_field()
    u_height: int | None = Field(None, ge=1, le=100, description="Rack units; the form suggests 53")
    width_mm: int | None = Field(None, **DIM, description="Outer width, mm")
    height_mm: int | None = Field(None, **DIM, description="Outer height, mm")
    depth_mm: int | None = Field(None, **DIM, description="Outer depth, mm")
    usable_width_mm: int | None = Field(None, gt=0)
    usable_depth_mm: int | None = Field(None, gt=0)
    rack_unit_width: RackUnitWidth | None = Field(None, description="Rack-unit (rail) width: 19in or 23in")
    rail_type: RailType | None = None
    rail_depth_min_mm: int | None = Field(None, gt=0)
    rail_depth_max_mm: int | None = Field(None, gt=0)
    front_door: Door | None = None
    rear_door: Door | None = None
    weight_capacity_kg: float | None = Field(None, gt=0, description="Stored only (no warnings yet)")
    color_hex: str | None = Field(None, pattern=COLOR)
    notes: str | None = Field(None, max_length=2000)


class CabinetProfileCreate(_Spec):
    manufacturer: str = Field(min_length=1, max_length=128)
    model: str = Field(min_length=1, max_length=128)
    name: str = Field("Standard", min_length=1, max_length=128, description="Variant name")


class CabinetProfileUpdate(_Spec):
    manufacturer: str | None = Field(None, min_length=1, max_length=128)
    model: str | None = Field(None, min_length=1, max_length=128)
    name: str | None = Field(None, min_length=1, max_length=128)
    expected_updated_at: datetime | None = Field(
        None, exclude=True, description="Optimistic lock: the updated_at you loaded; 409 version_conflict if it changed")


class CabinetCloneIn(InputModel):
    name: str | None = Field(None, min_length=1, max_length=128, description="Default: '<name> (copy)'")


class CabinetReadiness(BaseModel):
    ready: bool
    missing: list[str]


class CabinetProfile(OutputModel):
    id: int
    manufacturer: str
    model: str
    name: str
    status: Status
    version: int
    supersedes_cabinet_profile_id: int | None = None
    u_height: int | None = None
    width_mm: int | None = None
    height_mm: int | None = None
    depth_mm: int | None = None
    usable_width_mm: int | None = None
    usable_depth_mm: int | None = None
    rack_unit_width: str | None = None
    rail_type: str | None = None
    rail_depth_min_mm: int | None = None
    rail_depth_max_mm: int | None = None
    front_door: str | None = None
    rear_door: str | None = None
    weight_capacity_kg: float | None = None
    color_hex: str | None = None
    notes: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    created_by: str | None = None
    published_at: datetime | None = None
    published_by: str | None = None
    retired_at: datetime | None = None
    retired_by: str | None = None
    updated_by: str | None = Field(None, description="Actor of the latest audit event on this profile (edit, "
                                   "lifecycle or image change); no stored column")
    readiness: CabinetReadiness
    rack_count: int = Field(0, description="Cabinets using this profile; always 0 until cabinets link to profiles")
    front_image: ProfileImageRef | None = None
    rear_image: ProfileImageRef | None = None


class CabinetProfileEvent(BaseModel):
    id: int
    occurred_at: str = Field(description="ISO 8601 UTC with a trailing Z, like every datetime inside before/after")
    action: str
    actor_email: str | None = None
    before: dict | None = None
    after: dict | None = None
