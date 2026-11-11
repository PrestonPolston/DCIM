from datetime import UTC, datetime

from sqlalchemy import DateTime, func
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(UTC)


def ts_field(nullable: bool = True, **kwargs):
    return Field(default=None, nullable=nullable, sa_type=DateTime(timezone=True), **kwargs)


# created_at/updated_at on every table (UTC); updated_at refreshes on each UPDATE
class TimestampMixin(SQLModel):
    created_at: datetime | None = Field(
        default_factory=utcnow,
        nullable=False,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"server_default": func.now()},
    )
    updated_at: datetime | None = Field(
        default_factory=utcnow,
        nullable=False,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"server_default": func.now(), "onupdate": utcnow},
    )


# Soft delete (racks, devices): rows stay for history, hidden from lists
class SoftDeleteMixin(SQLModel):
    deleted_at: datetime | None = ts_field(index=True)
    deleted_by: str | None = None


# SQLite hands back naive datetimes (treat as UTC). Postgres may return them in
# the session time zone; always convert to UTC so responses are consistent.
def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def iso_z(value: datetime | None) -> str | None:
    """ISO 8601 UTC with a trailing Z, e.g. 2026-11-11T14:00:00Z."""
    value = as_utc(value)
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")
