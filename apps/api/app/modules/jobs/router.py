"""Job intake v1: /jobs (slice 1) + ePIF imports and open-item actions (slice 2).
Reads for every signed-in role; writes for technician/admin."""
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlmodel import Session, func, or_, select

from app.db import get_session
from app.modules.auth.deps import TECH, get_current_user
from app.modules.connections.models import CableRow, ConnectionRow
from app.modules.devices.models import DeviceRow
from app.modules.directory.models import ProjectReferenceRow as Ref, ProjectRow
from app.settings import Settings, get_settings
from app.modules.devices.csv_io import read_csv_body
from app.modules.jobs import epif
from app.modules.jobs import service as svc
from app.modules.jobs.models import UNRESOLVED, EpifRequestRow, ImportRowRow, JobImportRow, JobOpenItemRow as Item
from app.modules.jobs.schemas import (
    CommitResult, ImportKind, ItemNote, Job, JobClose, JobCloseResult, JobCreate, JobDetail, JobImport, JobImportDetail,
    JobReopen, JobResult, OpenItem, OpenItemResult,
)
from app.modules.locations.models import SiteRow
from app.modules.locations.service import get_or_404
from app.pagination import Pagination, contains
from app.timestamps import iso_z, utcnow

router = APIRouter(prefix="/jobs", tags=["jobs"], dependencies=[Depends(get_current_user)])


def _detail(session: Session, key: str) -> dict:
    p, dcreq = svc.get_job(session, key)
    return svc.job_out(session, [(p, dcreq)], detail=True)[0]


@router.post("", response_model=JobDetail, status_code=201, dependencies=[Depends(TECH)])
def create_job(payload: JobCreate, session: Session = Depends(get_session)):
    """Step 1 of intake: a new DCREQ creates the job (409 job_exists if it is already known)."""
    if payload.site_id is not None:
        get_or_404(session, SiteRow, payload.site_id, "Site")
    p = svc.create_job(session, payload.dcreq, payload.name, payload.description, payload.site_id)
    return _detail(session, str(p.id))


@router.get("", response_model=list[Job])
def list_jobs(response: Response, status: Literal["open", "closed"] | None = None,
              overdue: bool | None = Query(None, description="true: only current jobs open more than 30 days"),
              recently_closed: bool | None = Query(None, description="true: only jobs closed in the last 30 days"),
              q: str | None = Query(None, max_length=100, description="Contains-search on the DCREQ or the name"),
              page: Pagination = Depends(), session: Session = Depends(get_session)):
    now = utcnow()
    stmt = svc.jobs_query()
    if status:
        stmt = stmt.where(ProjectRow.status == status)
    cutoff = now - timedelta(days=svc.OVERDUE_DAYS)
    if overdue is True:
        stmt = stmt.where(ProjectRow.status == "open", ProjectRow.opened_at < cutoff)
    elif overdue is False:
        stmt = stmt.where(or_(ProjectRow.status != "open", ProjectRow.opened_at >= cutoff))
    closed_cutoff = now - timedelta(days=svc.RECENTLY_CLOSED_DAYS)
    if recently_closed is True:
        stmt = stmt.where(ProjectRow.status == "closed", ProjectRow.closed_at >= closed_cutoff)
    elif recently_closed is False:
        stmt = stmt.where(or_(ProjectRow.status != "closed", ProjectRow.closed_at < closed_cutoff))
    if q:
        stmt = stmt.where(or_(contains(Ref.ref, q.strip()), contains(ProjectRow.name, q.strip())))
    total = session.exec(select(func.count()).select_from(stmt.subquery())).one()
    response.headers["X-Total-Count"] = str(total)
    order = ((ProjectRow.closed_at.desc(), ProjectRow.id.desc()) if recently_closed is True
             else (ProjectRow.opened_at.desc(), ProjectRow.id.desc()))
    rows = session.exec(stmt.order_by(*order).offset(page.offset).limit(page.limit)).all()
    return svc.job_out(session, [(p, d) for p, d in rows])


@router.get("/{job_key}", response_model=JobDetail)
def get_job(job_key: str, session: Session = Depends(get_session)):
    """`job_key` is the numeric id or the DCREQ."""
    return _detail(session, job_key)


@router.post("/{job_key}/close", response_model=JobCloseResult, dependencies=[Depends(TECH)])
def close_job(job_key: str, payload: JobClose | None = None, session: Session = Depends(get_session)):
    """Close. With unresolved items this is 409 job_has_open_items unless acknowledge_open_items is true;
    then it closes and the 200 body carries the same warning."""
    payload = payload or JobClose()
    p, _ = svc.get_job(session, job_key)
    warning = svc.close_job(session, p, payload.acknowledge_open_items, payload.note)
    return {"job": _detail(session, str(p.id)), "warning": warning}


@router.post("/{job_key}/reopen", response_model=JobResult, dependencies=[Depends(TECH)])
def reopen_job(job_key: str, payload: JobReopen | None = None, session: Session = Depends(get_session)):
    """Reopen. opened_at (the 30-day clock) is not reset."""
    p, _ = svc.get_job(session, job_key)
    svc.reopen_job(session, p, (payload or JobReopen()).note)
    return {"job": _detail(session, str(p.id))}


ItemFilter = Literal["unresolved", "open", "deferred", "resolved", "dismissed", "all"]


@router.get("/{job_key}/open-items", response_model=list[OpenItem])
def list_open_items(job_key: str, response: Response, status: ItemFilter = "unresolved",
                    page: Pagination = Depends(), session: Session = Depends(get_session)):
    """The job's fill-later queue. unresolved = open + deferred."""
    p, dcreq = svc.get_job(session, job_key)
    stmt = _items_stmt().where(Item.project_id == p.id)
    if status == "unresolved":
        stmt = stmt.where(Item.status.in_(UNRESOLVED))
    elif status != "all":
        stmt = stmt.where(Item.status == status)
    total = session.exec(select(func.count()).select_from(stmt.subquery())).one()
    response.headers["X-Total-Count"] = str(total)
    rows = session.exec(stmt.order_by(Item.created_at, Item.id).offset(page.offset).limit(page.limit)).all()
    return [_item_out(p, dcreq, *r) for r in rows]


def _items_stmt():
    host = func.coalesce(DeviceRow.host_name, EpifRequestRow.requested_host_name)
    return (select(Item, host, CableRow.label, JobImportRow.filename, CableRow.trail)
            .join(DeviceRow, DeviceRow.id == Item.device_id, isouter=True)
            .join(EpifRequestRow, EpifRequestRow.id == Item.epif_request_id, isouter=True)
            .join(ConnectionRow, ConnectionRow.id == Item.connection_id, isouter=True)
            .join(CableRow, CableRow.id == func.coalesce(Item.cable_id, ConnectionRow.cable_id), isouter=True)
            .join(ImportRowRow, ImportRowRow.id == Item.import_row_id, isouter=True)
            .join(JobImportRow, JobImportRow.id == ImportRowRow.job_import_id, isouter=True))


def _item_out(p, dcreq, i, host, label, filename, trail) -> dict:
    return {
        "id": i.id, "job_id": p.id, "dcreq": dcreq, "item_type": i.item_type, "status": i.status,
        "target_field": i.target_field, "note": i.note, "source": i.source, "epif_request_id": i.epif_request_id,
        "device_id": i.device_id, "connection_id": i.connection_id, "cable_id": i.cable_id,
        "import_row_id": i.import_row_id, "filename": filename, "hostname": host, "cable_label": label,
        "cable_trail": trail,
        "created_at": iso_z(i.created_at), "created_by": i.created_by, "deferred_at": iso_z(i.deferred_at),
        "deferred_by": i.deferred_by, "resolved_at": iso_z(i.resolved_at), "resolved_by": i.resolved_by,
    }


ItemAction = Literal["defer", "undefer", "dismiss", "resolve"]


@router.post("/{job_key}/open-items/{item_id}/{action}", response_model=OpenItemResult,
             dependencies=[Depends(TECH)])
def open_item_action(job_key: str, item_id: int, action: ItemAction, payload: ItemNote | None = None,
                     session: Session = Depends(get_session)):
    """defer (open -> deferred, note optional), undefer (deferred -> open), dismiss (note REQUIRED: 422
    note_required), resolve (note optional). Resolved/dismissed items are final: 409 open_item_closed."""
    p, dcreq = svc.get_job(session, job_key)
    svc.item_action(session, p, item_id, action, (payload or ItemNote()).note)
    row = session.exec(_items_stmt().where(Item.id == item_id)).one()
    return {"item": _item_out(p, dcreq, *row), "job": _detail(session, str(p.id))}


# ---------------------------------------------------------------- imports (slice 2: ePIF)
def _import(session: Session, p: ProjectRow, import_id: int) -> JobImportRow:
    imp = session.get(JobImportRow, import_id)
    if imp is None or imp.project_id != p.id:
        raise svc.err(404, "import_not_found", "Import not found on this job")
    return imp


def _open_job(p: ProjectRow) -> None:
    if p.status != "open":
        raise svc.err(409, "job_closed", "This job is closed. Reopen it to import files.")


@router.post("/{job_key}/imports", response_model=JobImportDetail, status_code=201,
             dependencies=[Depends(TECH)],
             openapi_extra={"requestBody": {"required": True, "content": {"text/csv": {"schema": {"type": "string"}}}}},
             responses={200: {"model": JobImportDetail, "description": "Same file already uploaded to this job"}})
def upload_import(job_key: str, response: Response, kind: ImportKind = Query("epif"),
                  filename: str | None = Query(None, max_length=255),
                  text: str = Depends(read_csv_body), settings: Settings = Depends(get_settings),
                  session: Session = Depends(get_session)):
    """Stage a CSV (kind=epif or cable_matrix) on an EXISTING job (a CSV never creates a job) and return the
    validated preview.
    Body: the raw file with Content-Type: text/csv. Nothing live is written until commit."""
    p, dcreq = svc.get_job(session, job_key)
    _open_job(p)
    imp, reupload = epif.stage(session, p, dcreq, p.primary_dcreq_id, kind, text, filename, settings.csv_max_rows)
    if reupload:
        response.status_code = 200
    return epif.import_out(session, imp, reupload=reupload)


@router.get("/{job_key}/imports", response_model=list[JobImport])
def list_imports(job_key: str, response: Response, status: Literal["review", "committed", "abandoned"] | None = None,
                 page: Pagination = Depends(), session: Session = Depends(get_session)):
    p, _ = svc.get_job(session, job_key)
    stmt = select(JobImportRow).where(JobImportRow.project_id == p.id)
    if status:
        stmt = stmt.where(JobImportRow.status == status)
    total = session.exec(select(func.count()).select_from(stmt.subquery())).one()
    response.headers["X-Total-Count"] = str(total)
    rows = session.exec(stmt.order_by(JobImportRow.id.desc()).offset(page.offset).limit(page.limit)).all()
    return [epif.import_out(session, i, with_rows=False) for i in rows]


@router.get("/{job_key}/imports/{import_id}", response_model=JobImportDetail)
def get_import(job_key: str, import_id: int, session: Session = Depends(get_session)):
    """The preview: every staged row with its result and messages."""
    p, _ = svc.get_job(session, job_key)
    return epif.import_out(session, _import(session, p, import_id))


@router.post("/{job_key}/imports/{import_id}/abandon", response_model=JobImport, dependencies=[Depends(TECH)])
def abandon_import(job_key: str, import_id: int, session: Session = Depends(get_session)):
    p, _ = svc.get_job(session, job_key)
    imp = _import(session, p, import_id)
    epif.abandon(session, imp)
    return epif.import_out(session, imp, with_rows=False)


def _commit(session: Session, p: ProjectRow, dcreq: str, imports: list[JobImportRow]) -> dict:
    _open_job(p)
    result = epif.commit_batches(session, p, dcreq, p.primary_dcreq_id, imports)
    detail = _detail(session, str(p.id))
    return {"job": detail, "imports": [epif.import_out(session, session.get(JobImportRow, i.id), with_rows=False)
                                       for i in imports],
            "open_item_count": detail["unresolved_count"], **result}


@router.post("/{job_key}/imports/{import_id}/commit", response_model=CommitResult, dependencies=[Depends(TECH)])
def commit_import(job_key: str, import_id: int, session: Session = Depends(get_session)):
    """Commit one batch. Rows are re-validated; conflict rows are skipped with reasons, the rest is written in
    one change set. 409 import_not_in_review if the batch is committed or abandoned."""
    p, dcreq = svc.get_job(session, job_key)
    imp = _import(session, p, import_id)
    if imp.status != "review":
        raise svc.err(409, "import_not_in_review", f"This import is {imp.status}", status=imp.status)
    return _commit(session, p, dcreq, [imp])


@router.post("/{job_key}/commit", response_model=CommitResult, dependencies=[Depends(TECH)])
def commit_job(job_key: str, session: Session = Depends(get_session)):
    """Commit every batch of this job still in review, oldest first, in one change set.
    409 no_review_imports when there is nothing to commit."""
    p, dcreq = svc.get_job(session, job_key)
    imps = session.exec(select(JobImportRow).where(JobImportRow.project_id == p.id, JobImportRow.status == "review")
                        .order_by(JobImportRow.id)).all()
    if not imps:
        raise svc.err(409, "no_review_imports", "There are no imports in review on this job")
    return _commit(session, p, dcreq, list(imps))
