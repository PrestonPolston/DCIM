"""Job intake tables (docs/db/JOB_INTAKE.md §3-§4, p1_32/p1_33).

A job is a `projects` row keyed by its primary DCREQ (directory/models.py). These are the batch, staging-row
and open-item tables. `epif_request_id` and `device_psu_assignment_id` targets on open items land with the
ePIF/PDU tables (later slices); the one-target CHECK is swapped then.
"""
from datetime import datetime

from sqlalchemy import CheckConstraint, Index, Text, text
from sqlmodel import Field

from app.modules.jobs.dcreq import dcreq_sql
from app.timestamps import TimestampMixin, ts_field


def _in(col: str, values) -> str:
    return f"{col} IN (" + ",".join(f"'{v}'" for v in values) + ")"


IMPORT_KINDS = ("epif", "cable_matrix")
IMPORT_STATUSES = ("review", "committed", "abandoned")
ROW_RESULTS = ("ready", "warning", "held", "conflict", "committed", "skipped")
ITEM_TYPES = (
    "epif_not_uploaded", "cable_matrix_not_uploaded",
    "missing_hostname", "missing_profile", "profile_not_usable", "unresolved_cabinet", "missing_position",
    "missing_serial",
    "missing_psu", "psu_unparsed", "pdu_missing",
    "missing_port", "unresolved_hop", "missing_cable_label", "missing_trail", "media_missing", "ip_missing",
    "space_power_flag",
    "other",
)
ITEM_STATUSES = ("open", "deferred", "resolved", "dismissed")
UNRESOLVED = ("open", "deferred")
ITEM_SOURCES = ("epif", "cable_matrix", "manual")
TARGETS = ("device_id", "connection_id", "cable_id")
UNRESOLVED_SQL = "status IN ('open','deferred')"


class JobImportRow(TimestampMixin, table=True):
    """One uploaded file (ePIF or cable matrix) on a job. A CSV never creates the job."""
    __tablename__ = "job_imports"
    __table_args__ = (
        CheckConstraint(_in("kind", IMPORT_KINDS), name="kind"),
        CheckConstraint(_in("status", IMPORT_STATUSES), name="status"),
        CheckConstraint(dcreq_sql("dcreq"), name="dcreq_format"),
        CheckConstraint("sha256 IS NULL OR length(sha256) = 64", name="sha256"),
    )

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="projects.id", ondelete="RESTRICT", index=True)
    dcreq: str = Field(max_length=12, index=True)
    dcreq_reference_id: int = Field(foreign_key="project_references.id", ondelete="RESTRICT", index=True)
    kind: str = Field(max_length=16)
    filename: str | None = Field(default=None, max_length=255)
    sha256: str | None = Field(default=None, max_length=64, index=True)
    uploaded_by: str | None = Field(default=None, max_length=128)
    uploaded_at: datetime | None = ts_field()
    status: str = Field(default="review", max_length=12, sa_column_kwargs={"server_default": "review"})
    change_set_id: int | None = Field(default=None, foreign_key="change_sets.id", ondelete="SET NULL", index=True)


class ImportRowRow(TimestampMixin, table=True):
    """A staged CSV data row (1-based). Never holds secrets: secret/iLO headers reject the file."""
    __tablename__ = "import_rows"
    __table_args__ = (
        CheckConstraint(_in("result", ROW_RESULTS), name="result"),
        CheckConstraint("row_number >= 1", name="row_number"),
        Index("uq_import_rows_job_import_id_row_number", "job_import_id", "row_number", unique=True),
    )

    id: int | None = Field(default=None, primary_key=True)
    job_import_id: int = Field(foreign_key="job_imports.id", ondelete="CASCADE")
    row_number: int
    raw_json: str = Field(sa_type=Text)
    result: str = Field(max_length=16)
    messages_json: str | None = Field(default=None, sa_type=Text)
    device_id: int | None = Field(default=None, foreign_key="devices.id", ondelete="SET NULL", index=True)
    connection_id: int | None = Field(default=None, foreign_key="connections.id", ondelete="SET NULL", index=True)
    cable_id: int | None = Field(default=None, foreign_key="cables.id", ondelete="SET NULL", index=True)


_ONE_TARGET = " + ".join(f"CASE WHEN {c} IS NOT NULL THEN 1 ELSE 0 END" for c in TARGETS) + " <= 1"


class JobOpenItemRow(TimestampMixin, table=True):
    """A missing or unfinished fact on a job (fill-later queue). open + deferred = unresolved."""
    __tablename__ = "job_open_items"
    __table_args__ = (
        CheckConstraint(_in("item_type", ITEM_TYPES), name="item_type"),
        CheckConstraint(_in("status", ITEM_STATUSES), name="status"),
        CheckConstraint(_in("source", ITEM_SOURCES), name="source"),
        CheckConstraint("(status = 'deferred') = (deferred_at IS NOT NULL)", name="deferred"),
        CheckConstraint("(status IN ('open','deferred')) = (resolved_at IS NULL)", name="resolved"),
        CheckConstraint("status <> 'dismissed' OR (note IS NOT NULL AND length(trim(note)) > 0)",
                        name="dismiss_note"),
        CheckConstraint(_ONE_TARGET, name="one_target"),
        Index("uq_job_open_items_unresolved", "project_id", "item_type", text("coalesce(device_id, 0)"),
              text("coalesce(connection_id, 0)"), text("coalesce(cable_id, 0)"), text("coalesce(target_field, '')"),
              unique=True, sqlite_where=text(UNRESOLVED_SQL), postgresql_where=text(UNRESOLVED_SQL)),
        Index("ix_job_open_items_queue", "project_id", "status", "item_type", "created_at",
              sqlite_where=text(UNRESOLVED_SQL), postgresql_where=text(UNRESOLVED_SQL)),
    )

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="projects.id", ondelete="RESTRICT", index=True)
    item_type: str = Field(max_length=32)
    status: str = Field(default="open", max_length=16, sa_column_kwargs={"server_default": "open"})
    device_id: int | None = Field(default=None, foreign_key="devices.id", ondelete="SET NULL", index=True)
    connection_id: int | None = Field(default=None, foreign_key="connections.id", ondelete="SET NULL", index=True)
    cable_id: int | None = Field(default=None, foreign_key="cables.id", ondelete="SET NULL", index=True)
    import_row_id: int | None = Field(default=None, foreign_key="import_rows.id", ondelete="SET NULL", index=True)
    target_field: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, sa_type=Text)
    source: str = Field(max_length=16)
    created_by: str | None = Field(default=None, max_length=128)
    deferred_at: datetime | None = ts_field()
    deferred_by: str | None = Field(default=None, max_length=128)
    resolved_at: datetime | None = ts_field()
    resolved_by: str | None = Field(default=None, max_length=128)
    change_set_id: int | None = Field(default=None, foreign_key="change_sets.id", ondelete="SET NULL", index=True)
