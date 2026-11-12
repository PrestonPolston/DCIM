from sqlalchemy import Index, text
from sqlmodel import Field

from app.timestamps import TimestampMixin


# "Managed by" groups (D8/D15): point-of-contact teams; names unique case-insensitively
class GroupRow(TimestampMixin, table=True):
    __tablename__ = "groups"
    __table_args__ = (Index("uq_groups_name", text("lower(name)"), unique=True),)

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=255)


from datetime import date, datetime  # noqa: E402

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, Text, UniqueConstraint, func  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402

from app.modules.jobs.dcreq import dcreq_sql  # noqa: E402

from app.enums import ContactRole, RefKind, sql_in  # noqa: E402
from app.timestamps import ts_field, utcnow  # noqa: E402

JOB_STATUSES = ("open", "closed")
CURRENT_JOB = "status = 'open' AND deleted_at IS NULL"
RECENTLY_CLOSED_JOB = "status = 'closed' AND deleted_at IS NULL"


class VendorRow(TimestampMixin, table=True):
    __tablename__ = "vendors"
    __table_args__ = (Index("uq_vendors_name", text("lower(name)"), unique=True),)

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=255)


# Reusable people (PII: name/email/phone)
class ContactRow(TimestampMixin, table=True):
    __tablename__ = "contacts"
    __table_args__ = (
        CheckConstraint("name IS NOT NULL OR email IS NOT NULL", name="name_or_email"),
        Index("uq_contacts_email", text("lower(email)"), unique=True,
              sqlite_where=text("email IS NOT NULL"), postgresql_where=text("email IS NOT NULL")),
    )

    id: int | None = Field(default=None, primary_key=True)
    name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=64)
    organization: str | None = Field(default=None, max_length=255)
    vendor_id: int | None = Field(default=None, foreign_key="vendors.id", ondelete="SET NULL", index=True)


# A job (JOB_INTAKE.md §2) is a project with a primary DCREQ. status/opened_at/closed_* are p1_30.
class ProjectRow(TimestampMixin, table=True):
    __tablename__ = "projects"
    __table_args__ = (
        Index("uq_projects_intake_id", "intake_id", unique=True,
              sqlite_where=text("intake_id IS NOT NULL"), postgresql_where=text("intake_id IS NOT NULL")),
        CheckConstraint("status IN ('open','closed')", name="status"),
        CheckConstraint("(status = 'closed') = (closed_at IS NOT NULL)", name="closed"),
        Index("uq_projects_primary_dcreq_id", "primary_dcreq_id", unique=True,
              sqlite_where=text("primary_dcreq_id IS NOT NULL"),
              postgresql_where=text("primary_dcreq_id IS NOT NULL")),
        Index("ix_projects_current_opened_at", "opened_at",
              sqlite_where=text(CURRENT_JOB), postgresql_where=text(CURRENT_JOB)),
        Index("ix_projects_recently_closed", "closed_at",
              sqlite_where=text(RECENTLY_CLOSED_JOB), postgresql_where=text(RECENTLY_CLOSED_JOB)),
    )

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=255, index=True)
    description: str | None = Field(default=None, sa_type=Text)
    site_id: int | None = Field(default=None, foreign_key="sites.id", ondelete="RESTRICT", index=True)
    intake_id: str | None = Field(default=None, max_length=64)
    intake_date: date | None = None
    deleted_at: datetime | None = ts_field()
    status: str = Field(default="open", max_length=12, sa_column_kwargs={"server_default": "open"})
    # The 30-day clock: set once at creation (DCREQ entry), never rewritten (reopen keeps it)
    opened_at: datetime | None = Field(default_factory=utcnow, nullable=False, sa_type=DateTime(timezone=True),
                                       sa_column_kwargs={"server_default": func.now()})
    created_by: str | None = Field(default=None, max_length=128)  # the job creator (abandon rule, later)
    closed_at: datetime | None = ts_field()
    closed_by: str | None = Field(default=None, max_length=128)
    # use_alter: projects <-> project_references is a cycle (refs cascade from projects)
    primary_dcreq_id: int | None = Field(default=None, sa_column=Column(
        Integer, ForeignKey("project_references.id", ondelete="RESTRICT", use_alter=True,
                            name="fk_projects_primary_dcreq_id_project_references"), nullable=True))


# Ticket references (CHG/DCREQ/INC/OTHER) for a project
class ProjectReferenceRow(TimestampMixin, table=True):
    __tablename__ = "project_references"
    __table_args__ = (
        UniqueConstraint("project_id", "kind", "ref"),
        CheckConstraint(sql_in("kind", RefKind), name="kind"),
        CheckConstraint(f"kind <> 'DCREQ' OR ({dcreq_sql('ref')})", name="dcreq_format"),
        Index("ix_project_references_kind_ref", "kind", "ref"),
        Index("uq_project_references_dcreq", "ref", unique=True,
              sqlite_where=text("kind = 'DCREQ'"), postgresql_where=text("kind = 'DCREQ'")),
    )

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="projects.id", ondelete="CASCADE", index=True)
    kind: str = Field(max_length=8)
    ref: str = Field(max_length=64)


class ProjectContactRow(SQLModel, table=True):
    __tablename__ = "project_contacts"
    __table_args__ = (CheckConstraint(sql_in("contact_role", ContactRole), name="contact_role"),)

    project_id: int = Field(foreign_key="projects.id", ondelete="CASCADE", primary_key=True)
    contact_id: int = Field(foreign_key="contacts.id", ondelete="RESTRICT", primary_key=True)
    contact_role: str = Field(max_length=8, primary_key=True)
    title: str | None = Field(default=None, max_length=128)
