from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from app.validation import InputModel

JobStatus = Literal["open", "closed"]


class JobCreate(InputModel):
    coded_text_errors: ClassVar[bool] = True  # name / description / dcreq: single line, formula guard kept
    dcreq: str = Field(max_length=64, description="DCREQ000 + 4 digits (e.g. DCREQ0001234); trimmed and "
                                                  "uppercased by the service. A bad value is 422 dcreq_format.")
    name: str | None = Field(None, min_length=1, max_length=255, description="Defaults to the DCREQ")
    description: str | None = Field(None, max_length=10_000)
    site_id: int | None = Field(None, description="Alias building_id")


class JobClose(InputModel):
    multiline_fields: ClassVar[frozenset[str]] = frozenset({"note"})  # \n, \t; \r\n -> \n
    formula_allowed_fields: ClassVar[frozenset[str]] = frozenset({"note"})  # CSV exports neutralise on output
    coded_text_errors: ClassVar[bool] = True
    acknowledge_open_items: bool = Field(False, description="Required (true) to close a job that still has "
                                                            "unresolved (open or deferred) items")
    note: str | None = Field(None, max_length=2000)


class JobReopen(InputModel):
    multiline_fields: ClassVar[frozenset[str]] = frozenset({"note"})  # \n, \t; \r\n -> \n
    formula_allowed_fields: ClassVar[frozenset[str]] = frozenset({"note"})  # CSV exports neutralise on output
    coded_text_errors: ClassVar[bool] = True
    note: str | None = Field(None, max_length=2000)


class Job(BaseModel):
    id: int
    dcreq: str
    name: str
    description: str | None
    site_id: int | None
    primary_dcreq_id: int
    status: JobStatus
    opened_at: str = Field(description="UTC Z. Set once at DCREQ entry; never rewritten (reopen keeps it)")
    closed_at: str | None
    closed_by: str | None
    created_at: str
    updated_at: str
    created_by: str | None
    current: bool = Field(description="status = open (and not deleted)")
    overdue: bool = Field(description="current and opened_at more than 30 days ago")
    overdue_at: str = Field(description="opened_at + 30 days (UTC Z)")
    days_open: int = Field(description="Whole days since opened_at")
    recently_closed: bool = Field(description="closed, and closed_at within the last 30 days")
    days_since_closed: int | None
    unresolved_count: int = Field(description="Open + deferred items")
    deferred_count: int
    device_count: int = Field(description="Live devices with project_id = this job")
    connection_count: int = Field(description="Non-removed connections whose cable belongs to this job "
                                              "(cables.project_id; cable-matrix import)")


class JobDetail(Job):
    unresolved_by_type: dict[str, int]


class JobWarning(BaseModel):
    code: str
    message: str
    unresolved_count: int


class JobCloseResult(BaseModel):
    job: JobDetail
    warning: JobWarning | None


class JobResult(BaseModel):
    job: JobDetail


class OpenItem(BaseModel):
    id: int
    job_id: int
    dcreq: str
    item_type: str
    status: Literal["open", "deferred", "resolved", "dismissed"]
    target_field: str | None
    note: str | None
    source: Literal["epif", "cable_matrix", "manual"]
    epif_request_id: int | None
    device_id: int | None
    connection_id: int | None
    cable_id: int | None
    import_row_id: int | None
    filename: str | None = Field(description="Joined from the import batch (not stored)")
    hostname: str | None = Field(description="Joined from the device, else the ePIF request's requested name "
                                                        "(not stored)")
    cable_label: str | None = Field(description="Joined from the cable, or the connection's cable (not stored)")
    cable_trail: str | None = Field(description="Joined like cable_label (not stored)")
    created_at: str
    created_by: str | None
    deferred_at: str | None
    deferred_by: str | None
    resolved_at: str | None
    resolved_by: str | None


# ---- slice 2: imports + open-item actions ----
ImportKind = Literal["epif", "cable_matrix"]
RowResult = Literal["ready", "warning", "held", "conflict", "committed", "skipped"]


class RowMessage(BaseModel):
    code: str
    field: str | None
    message: str
    level: Literal["conflict", "held", "warning", "info"] = Field(
        description="conflict = row skipped; held = request kept, no device; warning = written + fill-later item")
    item_type: str | None = Field(None, description="Open item this message becomes on commit (if any)")
    target_field: str | None = None
    target: str | None = Field(None, description="Cable matrix: 'cable' when the item points at the cable "
                                                 "instead of the connection")


class ImportRow(BaseModel):
    id: int
    row_number: int = Field(description="1-based data row (header excluded)")
    result: RowResult
    messages: list[RowMessage]
    epif_id: str | None = Field(description="ePIF rows: the ePIF ID")
    matrix_id: str | None = Field(description="Cable-matrix rows: the ID column (-> cables.external_id)")
    action: str | None
    hostname: str | None = Field(description="ePIF: Name; cable matrix: A Name")
    row: str | None
    rack: str | None
    ru: str | None
    a: str | None = Field(description="Cable matrix: 'host:slot/port' as written for the A end")
    z: str | None = Field(description="Cable matrix: the Z end")
    trail: str | None
    cable_label: str | None
    cells: dict[str, str] = Field(description="The staged row by canonical column (secrets are never staged)")
    device_id: int | None
    epif_request_id: int | None
    connection_id: int | None
    cable_id: int | None


class ImportCounts(BaseModel):
    total: int
    ready: int
    warning: int
    held: int
    conflict: int
    committed: int
    skipped: int


class JobImport(BaseModel):
    id: int
    job_id: int
    dcreq: str
    kind: ImportKind
    filename: str | None
    sha256: str
    status: Literal["review", "committed", "abandoned"]
    uploaded_at: str
    uploaded_by: str | None
    change_set_id: int | None
    counts: ImportCounts
    reupload: Literal["review", "committed"] | None = Field(
        None, description="Set when the same file (sha256) was already uploaded to this job: 'review' = the "
                          "batch was re-validated in place; 'committed' = nothing new was staged")


class JobImportDetail(JobImport):
    rows: list[ImportRow]


class CommitRow(BaseModel):
    import_id: int
    kind: ImportKind
    row_number: int
    epif_id: str | None
    matrix_id: str | None = None
    hostname: str | None
    a: str | None = None
    z: str | None = None
    device_id: int | None = None
    epif_request_id: int | None = None
    connection_id: int | None = None
    cable_id: int | None = None
    cable_label: str | None = None
    reasons: list[RowMessage] = []


class CommitWarning(BaseModel):
    code: str
    message: str
    field: str | None
    item_type: str | None
    target_field: str | None
    import_id: int
    row_number: int
    hostname: str | None


class CommitResult(BaseModel):
    job: JobDetail
    imports: list[JobImport]
    committed: list[CommitRow]
    held: list[CommitRow]
    skipped: list[CommitRow] = Field(description="Conflict rows, not written; each has its reasons")
    warnings: list[CommitWarning]
    open_items_created: list[int]
    open_item_count: int = Field(description="The job's unresolved (open + deferred) items after the commit")
    resolved_item_ids: list[int] = Field(description="Items auto-resolved (e.g. epif_not_uploaded)")


class ItemNote(InputModel):
    multiline_fields: ClassVar[frozenset[str]] = frozenset({"note"})  # \n, \t; \r\n -> \n
    formula_allowed_fields: ClassVar[frozenset[str]] = frozenset({"note"})  # CSV exports neutralise on output
    coded_text_errors: ClassVar[bool] = True
    note: str | None = Field(None, max_length=2000)


class OpenItemResult(BaseModel):
    item: OpenItem
    job: JobDetail
