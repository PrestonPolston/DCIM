"""Job intake v1 (slice 1): /jobs. Reads for every signed-in role; writes for technician/admin."""
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlmodel import Session, func, or_, select

from app.db import get_session
from app.modules.auth.deps import TECH, get_current_user
from app.modules.connections.models import CableRow
from app.modules.devices.models import DeviceRow
from app.modules.directory.models import ProjectReferenceRow as Ref, ProjectRow
from app.modules.jobs import service as svc
from app.modules.jobs.models import UNRESOLVED, ImportRowRow, JobImportRow, JobOpenItemRow as Item
from app.modules.jobs.schemas import Job, JobClose, JobCloseResult, JobCreate, JobDetail, JobReopen, JobResult, OpenItem
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
    """The job's fill-later queue (read-only in this slice). unresolved = open + deferred."""
    p, dcreq = svc.get_job(session, job_key)
    stmt = (select(Item, DeviceRow.host_name, CableRow.label, JobImportRow.filename)
            .join(DeviceRow, DeviceRow.id == Item.device_id, isouter=True)
            .join(CableRow, CableRow.id == Item.cable_id, isouter=True)
            .join(ImportRowRow, ImportRowRow.id == Item.import_row_id, isouter=True)
            .join(JobImportRow, JobImportRow.id == ImportRowRow.job_import_id, isouter=True)
            .where(Item.project_id == p.id))
    if status == "unresolved":
        stmt = stmt.where(Item.status.in_(UNRESOLVED))
    elif status != "all":
        stmt = stmt.where(Item.status == status)
    total = session.exec(select(func.count()).select_from(stmt.subquery())).one()
    response.headers["X-Total-Count"] = str(total)
    rows = session.exec(stmt.order_by(Item.created_at, Item.id).offset(page.offset).limit(page.limit)).all()
    return [{
        "id": i.id, "job_id": p.id, "dcreq": dcreq, "item_type": i.item_type, "status": i.status,
        "target_field": i.target_field, "note": i.note, "source": i.source, "device_id": i.device_id,
        "connection_id": i.connection_id, "cable_id": i.cable_id, "import_row_id": i.import_row_id,
        "filename": filename, "hostname": host, "cable_label": label,
        "created_at": iso_z(i.created_at), "created_by": i.created_by, "deferred_at": iso_z(i.deferred_at),
        "deferred_by": i.deferred_by, "resolved_at": iso_z(i.resolved_at), "resolved_by": i.resolved_by,
    } for i, host, label, filename in rows]
