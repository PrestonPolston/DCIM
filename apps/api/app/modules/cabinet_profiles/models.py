"""Cabinet profiles (MIGRATION_SPEC_CABINET_PROFILES.md, p1_28/p1_29): the cabinet alone, admin-typed, mm only."""
from datetime import datetime

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, LargeBinary, Numeric, Text, text
from sqlmodel import Field, UniqueConstraint

from app.modules.images.models import MAX_BYTES, MAX_PX
from app.timestamps import TimestampMixin

STATUSES = ("draft", "published", "retired")
RACK_UNIT_WIDTHS = ("19in", "23in")
RAIL_TYPES = ("square_hole", "round_hole", "threaded")
DOORS = ("none", "perforated", "solid", "split")


def _in(col: str, values) -> str:
    return f"{col} IN (" + ",".join(f"'{v}'" for v in values) + ")"


class CabinetProfileRow(TimestampMixin, table=True):
    __tablename__ = "cabinet_profiles"
    __table_args__ = (
        CheckConstraint(_in("status", STATUSES), name="status"),
        CheckConstraint("length(trim(manufacturer)) > 0", name="manufacturer_nonempty"),
        CheckConstraint("length(trim(model)) > 0", name="model_nonempty"),
        CheckConstraint("length(trim(name)) > 0", name="name_nonempty"),
        CheckConstraint("version >= 1", name="version"),
        CheckConstraint("u_height IS NULL OR u_height BETWEEN 1 AND 100", name="u_height"),
        CheckConstraint("(width_mm IS NULL OR width_mm > 0) AND (height_mm IS NULL OR height_mm > 0) AND "
                        "(depth_mm IS NULL OR depth_mm > 0)", name="dims"),
        CheckConstraint("(usable_width_mm IS NULL OR (usable_width_mm > 0 AND (width_mm IS NULL OR usable_width_mm "
                        "<= width_mm))) AND (usable_depth_mm IS NULL OR (usable_depth_mm > 0 AND (depth_mm IS NULL "
                        "OR usable_depth_mm <= depth_mm)))", name="usable"),
        CheckConstraint("rack_unit_width IS NULL OR " + _in("rack_unit_width", RACK_UNIT_WIDTHS), name="rack_unit_width"),
        CheckConstraint("rail_type IS NULL OR " + _in("rail_type", RAIL_TYPES), name="rail_type"),
        CheckConstraint("(rail_depth_min_mm IS NULL OR rail_depth_min_mm > 0) AND (rail_depth_max_mm IS NULL OR "
                        "rail_depth_max_mm > 0) AND (rail_depth_min_mm IS NULL OR rail_depth_max_mm IS NULL OR "
                        "rail_depth_min_mm <= rail_depth_max_mm) AND (rail_depth_max_mm IS NULL OR depth_mm IS NULL "
                        "OR rail_depth_max_mm <= depth_mm)", name="rail_depth"),
        CheckConstraint("front_door IS NULL OR " + _in("front_door", DOORS), name="front_door"),
        CheckConstraint("rear_door IS NULL OR " + _in("rear_door", DOORS), name="rear_door"),
        CheckConstraint("weight_capacity_kg IS NULL OR weight_capacity_kg > 0", name="weight_capacity_kg"),
        CheckConstraint("color_hex IS NULL OR (length(color_hex) = 7 AND substr(color_hex, 1, 1) = '#')",
                        name="color_hex"),
        CheckConstraint("status = 'draft' OR (u_height IS NOT NULL AND width_mm IS NOT NULL AND height_mm IS NOT "
                        "NULL AND depth_mm IS NOT NULL AND rack_unit_width IS NOT NULL)", name="publish_ready"),
        CheckConstraint("status = 'draft' OR published_at IS NOT NULL", name="published_at"),
        CheckConstraint("(status = 'retired') = (retired_at IS NOT NULL)", name="retired"),
        CheckConstraint("supersedes_cabinet_profile_id IS NULL OR supersedes_cabinet_profile_id <> id",
                        name="not_self"),
        Index("uq_cabinet_profiles_manufacturer_model_name", text("lower(manufacturer)"), text("lower(model)"),
              text("lower(name)"), unique=True),
        Index("ix_cabinet_profiles_status", "status"),
        Index("ix_cabinet_profiles_supersedes_cabinet_profile_id", "supersedes_cabinet_profile_id"),
        UniqueConstraint("id", "u_height", name="uq_cabinet_profiles_id_u_height"),
    )

    id: int | None = Field(default=None, primary_key=True)
    manufacturer: str = Field(max_length=128)
    model: str = Field(max_length=128)
    name: str = Field(default="Standard", max_length=128, sa_column_kwargs={"server_default": "Standard"})
    status: str = Field(default="draft", max_length=12, sa_column_kwargs={"server_default": "draft"})
    version: int = Field(default=1, sa_column_kwargs={"server_default": "1"})
    supersedes_cabinet_profile_id: int | None = Field(default=None, sa_column=Column(
        Integer, ForeignKey("cabinet_profiles.id", name="fk_cabinet_profiles_supersedes_id_cabinet_profiles", ondelete="RESTRICT")))
    u_height: int | None = None
    width_mm: int | None = None
    height_mm: int | None = None
    depth_mm: int | None = None
    usable_width_mm: int | None = None
    usable_depth_mm: int | None = None
    rack_unit_width: str | None = Field(default=None, max_length=8)
    rail_type: str | None = Field(default=None, max_length=16)
    rail_depth_min_mm: int | None = None
    rail_depth_max_mm: int | None = None
    front_door: str | None = Field(default=None, max_length=12)
    rear_door: str | None = Field(default=None, max_length=12)
    weight_capacity_kg: float | None = Field(default=None, sa_type=Numeric(8, 2, asdecimal=False))
    color_hex: str | None = Field(default=None, max_length=7)
    notes: str | None = Field(default=None, sa_type=Text)
    created_by: str | None = Field(default=None, max_length=128)
    published_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    published_by: str | None = Field(default=None, max_length=128)
    retired_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    retired_by: str | None = Field(default=None, max_length=128)


class CabinetProfileImageRow(TimestampMixin, table=True):
    __tablename__ = "cabinet_profile_images"
    __table_args__ = (
        UniqueConstraint("cabinet_profile_id", "face", "variant",
                         name="uq_cabinet_profile_images_cabinet_profile_id_face_variant"),
        CheckConstraint("face IN ('front','rear')", name="face"),
        CheckConstraint("variant IN ('original','thumb','tex')", name="variant"),
        CheckConstraint("content_type IN ('image/png','image/jpeg','image/webp')", name="content_type"),
        CheckConstraint(f"byte_size BETWEEN 1 AND {MAX_BYTES}", name="byte_size"),
        CheckConstraint(f"width_px BETWEEN 1 AND {MAX_PX} AND height_px BETWEEN 1 AND {MAX_PX}", name="dims"),
        CheckConstraint("variant = 'original' OR (width_px <= 1024 AND height_px <= 1024)", name="derived_dims"),
        CheckConstraint("length(sha256) = 64", name="sha256"),
        CheckConstraint("storage IN ('db','object')", name="storage"),
        CheckConstraint("(storage = 'db' AND data IS NOT NULL) OR (storage = 'object' AND object_key IS NOT NULL)",
                        name="payload"),
        CheckConstraint("version >= 1", name="version"),
        Index("ix_cabinet_profile_images_sha256", "sha256"),
    )

    id: int | None = Field(default=None, primary_key=True)
    cabinet_profile_id: int = Field(foreign_key="cabinet_profiles.id", ondelete="CASCADE")
    face: str = Field(max_length=8)
    variant: str = Field(default="original", max_length=16, sa_column_kwargs={"server_default": "original"})
    content_type: str = Field(max_length=32)
    byte_size: int
    width_px: int
    height_px: int
    sha256: str = Field(max_length=64)
    storage: str = Field(default="db", max_length=8, sa_column_kwargs={"server_default": "db"})
    data: bytes | None = Field(default=None, sa_type=LargeBinary)
    object_key: str | None = Field(default=None, max_length=512)
    version: int = Field(default=1, sa_column_kwargs={"server_default": "1"})
    original_filename: str | None = Field(default=None, max_length=255)
    uploaded_by: str | None = Field(default=None, max_length=128)
