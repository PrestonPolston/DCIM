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


# SQLite hands back naive datetimes; treat them as UTC
def as_utc(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
