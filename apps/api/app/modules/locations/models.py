from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, false, text
from sqlmodel import Field, UniqueConstraint

from app.enums import Orientation, sql_in
from app.timestamps import SoftDeleteMixin, TimestampMixin

ORIENTATION_CHECK = "orientation IS NULL OR " + sql_in("orientation", Orientation)
POS_CHECK = "(pos_x IS NULL OR pos_x >= 0) AND (pos_y IS NULL OR pos_y >= 0)"


# Database tables for the location hierarchy: site -> hall -> row -> rack
class SiteRow(TimestampMixin, table=True):
    __tablename__ = "sites"
    __table_args__ = (
        # at most one default site (used when a hall/CSV row names no site)
        Index("uq_sites_default", "is_default", unique=True,
              sqlite_where=text("is_default"), postgresql_where=text("is_default")),
    )

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    address: str | None = None
    is_default: bool = Field(default=False, sa_column_kwargs={"server_default": false()})


class HallRow(TimestampMixin, table=True):
    __tablename__ = "halls"
    __table_args__ = (
        UniqueConstraint("site_id", "name"),
        CheckConstraint("aisle_axis IS NULL OR aisle_axis IN ('x','y')", name="aisle_axis"),
        CheckConstraint("odd_side IS NULL OR odd_side IN ('low','high')", name="odd_side"),
    )

    id: int | None = Field(default=None, primary_key=True)
    site_id: int = Field(foreign_key="sites.id", ondelete="RESTRICT", index=True)
    name: str = Field(index=True)
    # floor-plan hints: the center aisle runs along this grid axis; odd rows sit on the low/high side
    aisle_axis: str | None = Field(default=None, max_length=1)
    odd_side: str | None = Field(default=None, max_length=4)


class RackRowRow(TimestampMixin, table=True):
    __tablename__ = "rows"
    __table_args__ = (
        UniqueConstraint("hall_id", "name"),
        UniqueConstraint("id", "hall_id", name="uq_rows_id_hall_id"),  # target of racks' composite FK (P1-10)
        CheckConstraint(ORIENTATION_CHECK, name="orientation"),
        CheckConstraint(POS_CHECK, name="pos"),
    )

    id: int | None = Field(default=None, primary_key=True)
    hall_id: int = Field(foreign_key="halls.id", ondelete="RESTRICT", index=True)
    name: str = Field(index=True)
    pos_x: int | None = None  # floor grid column
    pos_y: int | None = None  # floor grid row
    orientation: str | None = None  # N/E/S/W: direction the front faces


class RackRow(TimestampMixin, SoftDeleteMixin, table=True):
    __tablename__ = "racks"
    __table_args__ = (
        # names are unique per row among live (not soft-deleted) racks
        Index(
            "uq_racks_row_id_name", "row_id", "name", unique=True,
            sqlite_where=text("deleted_at IS NULL"), postgresql_where=text("deleted_at IS NULL"),
        ),
        CheckConstraint("u_height BETWEEN 1 AND 100", name="u_height"),
        CheckConstraint(ORIENTATION_CHECK, name="orientation"),
        CheckConstraint(POS_CHECK, name="pos"),
        # P1-10 (DESIGN §2.3): denormalized hall, kept consistent with the row by a composite FK
        ForeignKeyConstraint(["row_id", "hall_id"], ["rows.id", "rows.hall_id"],
                             name="fk_racks_row_id_hall_id_rows", ondelete="RESTRICT", onupdate="CASCADE"),
        Index("uq_racks_hall_id_pos_x_pos_y", "hall_id", "pos_x", "pos_y", unique=True,
              sqlite_where=text("deleted_at IS NULL"), postgresql_where=text("deleted_at IS NULL")),
        Index("ix_racks_hall_id_id", "hall_id", "id"),
    )

    id: int | None = Field(default=None, primary_key=True)
    row_id: int = Field(foreign_key="rows.id", ondelete="RESTRICT", index=True)
    hall_id: int | None = Field(default=None, nullable=False)  # = rows.hall_id; set from the row on insert
    name: str = Field(index=True)
    u_height: int = Field(default=53, sa_column_kwargs={"server_default": "53"})  # standard cabinet: 53 RU
    pos_x: int | None = None  # floor grid column
    pos_y: int | None = None  # floor grid row
    orientation: str | None = None  # N/E/S/W; null = inherit the row's
