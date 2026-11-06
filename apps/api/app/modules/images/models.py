"""Profile face images (D16, PROFILE_IMAGES.md §3): DB blobs, one row per profile + face + variant."""
from sqlalchemy import CheckConstraint, Index, LargeBinary, UniqueConstraint, false  # noqa: F401
from sqlmodel import Field

from app.timestamps import TimestampMixin

MAX_BYTES = 2 * 1024 * 1024
MAX_PX = 4096
CONTENT_TYPES = ("image/png", "image/jpeg", "image/webp")


class ProfileImageRow(TimestampMixin, table=True):
    __tablename__ = "profile_images"
    __table_args__ = (
        UniqueConstraint("profile_id", "face", "variant", name="uq_profile_images_profile_id_face_variant"),
        CheckConstraint("face IN ('front','rear')", name="face"),
        CheckConstraint("variant IN ('original','thumb','tex')", name="variant"),
        CheckConstraint("variant = 'original' OR (width_px <= 1024 AND height_px <= 1024)", name="derived_dims"),
        CheckConstraint("content_type IN ('image/png','image/jpeg','image/webp')", name="content_type"),
        CheckConstraint(f"byte_size BETWEEN 1 AND {MAX_BYTES}", name="byte_size"),
        CheckConstraint(f"width_px BETWEEN 1 AND {MAX_PX} AND height_px BETWEEN 1 AND {MAX_PX}", name="dims"),
        CheckConstraint("length(sha256) = 64", name="sha256"),
        CheckConstraint("storage IN ('db','object')", name="storage"),
        CheckConstraint("(storage = 'db' AND data IS NOT NULL) OR (storage = 'object' AND object_key IS NOT NULL)",
                        name="payload"),
        CheckConstraint("version >= 1", name="version"),
        Index("ix_profile_images_sha256", "sha256"),
    )

    id: int | None = Field(default=None, primary_key=True)
    profile_id: int = Field(foreign_key="device_type_profiles.id", ondelete="CASCADE")
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
