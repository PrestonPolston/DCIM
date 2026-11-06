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

from sqlalchemy import CheckConstraint, Text, UniqueConstraint  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402

from app.enums import ContactRole, RefKind, sql_in  # noqa: E402
from app.timestamps import ts_field  # noqa: E402


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


class ProjectRow(TimestampMixin, table=True):
    __tablename__ = "projects"
    __table_args__ = (
        Index("uq_projects_intake_id", "intake_id", unique=True,
              sqlite_where=text("intake_id IS NOT NULL"), postgresql_where=text("intake_id IS NOT NULL")),
    )

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=255, index=True)
    description: str | None = Field(default=None, sa_type=Text)
    site_id: int | None = Field(default=None, foreign_key="sites.id", ondelete="RESTRICT", index=True)
    intake_id: str | None = Field(default=None, max_length=64)
    intake_date: date | None = None
    deleted_at: datetime | None = ts_field()


# Ticket references (CHG/DCREQ/INC/OTHER) for a project
class ProjectReferenceRow(TimestampMixin, table=True):
    __tablename__ = "project_references"
    __table_args__ = (
        UniqueConstraint("project_id", "kind", "ref"),
        CheckConstraint(sql_in("kind", RefKind), name="kind"),
        Index("ix_project_references_kind_ref", "kind", "ref"),
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
