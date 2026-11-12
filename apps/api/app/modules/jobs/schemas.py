from typing import Literal

from pydantic import BaseModel, Field

from app.validation import InputModel

JobStatus = Literal["open", "closed"]


class JobCreate(InputModel):
    dcreq: str = Field(max_length=64, description="DCREQ000 + 4 digits (e.g. DCREQ0001234); trimmed and "
                                                  "uppercased by the service. A bad value is 422 dcreq_format.")
    name: str | None = Field(None, min_length=1, max_length=255, description="Defaults to the DCREQ")
    description: str | None = Field(None, max_length=10_000)
    site_id: int | None = Field(None, description="Alias building_id")


class JobClose(InputModel):
    acknowledge_open_items: bool = Field(False, description="Required (true) to close a job that still has "
                                                            "unresolved (open or deferred) items")
    note: str | None = Field(None, max_length=2000)


class JobReopen(InputModel):
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
    device_id: int | None
    connection_id: int | None
    cable_id: int | None
    import_row_id: int | None
    filename: str | None = Field(description="Joined from the import batch (not stored)")
    hostname: str | None = Field(description="Joined from the device (not stored)")
    cable_label: str | None = Field(description="Joined from the cable (not stored)")
    created_at: str
    created_by: str | None
    deferred_at: str | None
    deferred_by: str | None
    resolved_at: str | None
    resolved_by: str | None
