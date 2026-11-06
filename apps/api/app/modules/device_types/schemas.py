from typing import ClassVar
from app.modules.images.refs import ProfileImageRef
from app.enums import AssetTypeLiteral
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.enums import (AirflowLiteral, MountingLiteral, PowerTypeLiteral, ProfileOrientationLiteral,
                       ProfileStatusLiteral)
from datetime import datetime
from app.modules.devices.schemas import COLOR

from app.units import UnitInput, UnitLiteral, unit_field
from app.validation import InputModel, OutputModel


# Data the client sends to create a device type
class DeviceTypeCreate(InputModel):
    manufacturer: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100, description="Model name")
    u_height: int = Field(1, ge=1, le=100)
    is_full_depth: bool = True
    asset_type: AssetTypeLiteral | None = Field(None, description="Default asset type for its devices")
    eos_date: date | None = Field(None, description="Default end of support for its devices")


# Data the client sends to change a device type (any subset of fields)
class DeviceTypeUpdate(InputModel):
    manufacturer: str | None = Field(None, min_length=1, max_length=100)
    name: str | None = Field(None, min_length=1, max_length=100)
    u_height: int | None = Field(None, ge=1, le=100)
    is_full_depth: bool | None = None
    asset_type: AssetTypeLiteral | None = Field(None)
    eos_date: date | None = None


# Data the API returns
class DeviceType(OutputModel, DeviceTypeCreate):
    model_config = OutputModel.model_config
    id: int


# Shapes of the profile JSON (extra keys such as x_mm/y_mm are kept)
class PortSpec(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str = Field(min_length=1, max_length=64)
    kind: str | None = Field(None, max_length=16)
    connector: str | None = Field(None, max_length=32)
    speed_mbps: int | None = Field(None, gt=0, description="Per-port speed")
    face: str | None = Field(None, pattern="^(front|rear)$")


class PowerSpec(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str = Field(min_length=1, max_length=64)
    connector: str | None = Field(None, max_length=32)
    voltage: int | None = Field(None, gt=0)
    max_draw_w: int | None = Field(None, ge=0)
    typical_draw_w: int | None = Field(None, ge=0)
    redundancy_group: str | None = Field(None, max_length=32)


class ProfileExtras(InputModel):
    color_hex: str | None = Field(None, pattern=COLOR, description="Default device color #RRGGBB")
    airflow: AirflowLiteral | None = None
    power_type: PowerTypeLiteral | None = None
    orientation: ProfileOrientationLiteral | None = Field(
        None, description="port_front | power_front (which side the ports face); required to publish a switch")


# Device profiles (physical/rendering data) under /device-types/{id}/profiles
class ProfileFields(ProfileExtras):
    mounting: MountingLiteral | None = None
    weight_kg: float | None = Field(None, gt=0, le=2000, description="Optional")
    width_mm: float | None = Field(None, gt=0)
    height_mm: float | None = Field(None, gt=0)
    depth_mm: float | None = Field(None, gt=0)
    is_full_depth: bool = True
    faces: list[str] = ["front", "rear"]
    ports: list[PortSpec] | None = None
    power: list[PowerSpec] | None = None
    model_refs: list | dict | None = Field(None, description="URLs/references to 2D/3D assets")


class DeviceProfileCreate(ProfileFields):
    name: str = Field(min_length=1)
    is_default: bool = False


class DeviceProfileCreateRequest(UnitInput, DeviceProfileCreate):
    MM_FIELDS: ClassVar[tuple[str, ...]] = ("width_mm", "height_mm", "depth_mm")
    MM_STEP: ClassVar[str] = "0.1"
    unit: UnitLiteral | None = unit_field()
    # Add-profile flow: sets the model's asset_type when it has none (the type is where asset_type lives)
    asset_type: AssetTypeLiteral | None = Field(None, description="Model asset type, if the model has none yet")


class DeviceProfileUpdate(UnitInput, ProfileExtras):
    MM_FIELDS: ClassVar[tuple[str, ...]] = ("width_mm", "height_mm", "depth_mm")
    MM_STEP: ClassVar[str] = "0.1"
    unit: UnitLiteral | None = unit_field()
    name: str | None = Field(None, min_length=1)
    mounting: MountingLiteral | None = None
    weight_kg: float | None = Field(None, gt=0, le=2000)
    is_default: bool | None = None
    width_mm: float | None = Field(None, gt=0)
    height_mm: float | None = Field(None, gt=0)
    depth_mm: float | None = Field(None, gt=0)
    is_full_depth: bool | None = None
    faces: list[str] | None = None
    ports: list[PortSpec] | None = None
    power: list[PowerSpec] | None = None
    model_refs: list | dict | None = None


class Readiness(BaseModel):
    ready: bool
    missing: list[str] = Field(description="Fields still needed before publish")
    messages: dict[str, str] = Field(default_factory=dict, description="Human-readable reason per missing field")
    flags: list[str] = Field(default_factory=list, description="Published-but-unusable issues, e.g. rear_image_missing")


class DeviceProfile(OutputModel, DeviceProfileCreate):
    model_config = OutputModel.model_config
    usable: bool = Field(False, description="Published and complete: can be used for new devices/profile switches")
    usable_issue: str | None = Field(None, description="First reason it isn't usable (= usable_issues[0])")
    usable_issues: list[str] = Field(default_factory=list,
                                     description="All reasons, e.g. rear_image_missing, orientation_missing, profile_draft")
    id: int
    device_type_id: int
    u_height: int  # always the device type's u_height
    status: ProfileStatusLiteral = "draft"
    published_at: datetime | None = None
    retired_at: datetime | None = None
    published_by: str | None = None
    version: int = 1
    supersedes_profile_id: int | None = None
    readiness: Readiness | None = None
    front_image: ProfileImageRef | None = None
    rear_image: ProfileImageRef | None = None
