"""Job intake v1, slice 1 (JOB_INTAKE.md §2, §2.1): create a job from a typed DCREQ, read, close, reopen.

Locked (Preston, 2026-11-12): a new DCREQ creates the job; a duplicate is a hard 409 (`job_exists`); one DCREQ
per job; close with unresolved items needs an explicit acknowledgement; the 30-day clock is `opened_at`, set at
DCREQ entry and never rewritten (reopen keeps it).
"""
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.modules.audit.service import record_audit
from app.modules.devices.models import DeviceRow
from app.modules.directory.models import ProjectReferenceRow as Ref, ProjectRow
from app.modules.history.service import new_change_set
from app.modules.jobs.dcreq import normalize_dcreq
from app.modules.jobs.models import UNRESOLVED, JobOpenItemRow as Item
from app.timestamps import as_utc, iso_z, utcnow

OVERDUE_DAYS = 30  # open more than 30 days since DCREQ entry
RECENTLY_CLOSED_DAYS = 30  # closed jobs stay on Home for 30 days after closed_at
SKIP_FILE_ITEMS = ("epif_not_uploaded", "cable_matrix_not_uploaded")
DCREQ_HINT = "Enter a DCREQ like DCREQ0001234 (DCREQ000 + 4 digits)."


def err(status_code: int, code: str, message: str, **extra) -> HTTPException:
    return HTTPException(status_code, {"code": code, "message": message, **extra})


def actor(session: Session) -> str | None:
    return getattr(session.info.get("user"), "email", None)


def require_dcreq(value) -> str:
    norm = normalize_dcreq(value)
    if norm is None:  # the value is never echoed back (R-1)
        raise err(422, "dcreq_format", DCREQ_HINT, field="dcreq")
    return norm


def existing_job_detail(session: Session, ref: Ref) -> dict:
    p = session.get(ProjectRow, ref.project_id)
    existing = {"id": p.id, "dcreq": ref.ref, "name": p.name, "status": p.status,
                "is_job": p.primary_dcreq_id is not None, "deleted": p.deleted_at is not None}
    return {"code": "job_exists",
            "message": f"{ref.ref} is already a job ({p.name}, {p.status}). Attaching more work to that job "
                       "isn't available yet.",
            "existing": existing}


def find_dcreq(session: Session, dcreq: str) -> Ref | None:
    with session.no_autoflush:
        return session.exec(select(Ref).where(Ref.kind == "DCREQ", Ref.ref == dcreq)).first()


# ---- computed fields (never stored: they would go stale at midnight) ----
def computed(p: ProjectRow, now: datetime) -> dict:
    opened, closed = as_utc(p.opened_at), as_utc(p.closed_at)
    current = p.status == "open" and p.deleted_at is None
    return {
        "current": current,
        "overdue": current and opened < now - timedelta(days=OVERDUE_DAYS),
        "overdue_at": iso_z(opened + timedelta(days=OVERDUE_DAYS)),
        "days_open": max(0, (now - opened).days),
        "recently_closed": p.status == "closed" and p.deleted_at is None and closed is not None
                           and closed >= now - timedelta(days=RECENTLY_CLOSED_DAYS),
        "days_since_closed": max(0, (now - closed).days) if closed is not None else None,
    }


def item_counts(session: Session, ids: list[int]) -> dict[int, dict[str, int]]:
    """{project_id: {item_type: n, ...}} for unresolved items, plus '__deferred'. One query."""
    out: dict[int, dict[str, int]] = {i: {} for i in ids}
    if not ids:
        return out
    rows = session.exec(select(Item.project_id, Item.item_type, Item.status, func.count())
                        .where(Item.project_id.in_(ids), Item.status.in_(UNRESOLVED))
                        .group_by(Item.project_id, Item.item_type, Item.status)).all()
    for pid, itype, status, n in rows:
        d = out[pid]
        d[itype] = d.get(itype, 0) + n
        if status == "deferred":
            d["__deferred"] = d.get("__deferred", 0) + n
    return out


def device_counts(session: Session, ids: list[int]) -> dict[int, int]:
    if not ids:
        return {}
    rows = session.exec(select(DeviceRow.project_id, func.count()).where(
        DeviceRow.project_id.in_(ids), DeviceRow.deleted_at.is_(None)).group_by(DeviceRow.project_id)).all()
    return dict(rows)


def job_out(session: Session, jobs: list[tuple[ProjectRow, str]], detail: bool = False) -> list[dict]:
    now = datetime.now(UTC)
    ids = [p.id for p, _ in jobs]
    items, devices = item_counts(session, ids), device_counts(session, ids)
    res = []
    for p, dcreq in jobs:
        counts = dict(items.get(p.id, {}))
        deferred = counts.pop("__deferred", 0)
        d = {
            "id": p.id, "dcreq": dcreq, "name": p.name, "description": p.description, "site_id": p.site_id,
            "primary_dcreq_id": p.primary_dcreq_id, "status": p.status,
            "opened_at": iso_z(p.opened_at), "closed_at": iso_z(p.closed_at), "closed_by": p.closed_by,
            "created_at": iso_z(p.created_at), "updated_at": iso_z(p.updated_at), "created_by": p.created_by,
            **computed(p, now),
            "unresolved_count": sum(counts.values()), "deferred_count": deferred,
            "device_count": devices.get(p.id, 0),
        }
        if detail:
            d["unresolved_by_type"] = dict(sorted(counts.items()))
        res.append(d)
    return res


def jobs_query():
    """Jobs = live projects that have a primary DCREQ (legacy projects without one are not jobs)."""
    return (select(ProjectRow, Ref.ref).join(Ref, Ref.id == ProjectRow.primary_dcreq_id)
            .where(ProjectRow.deleted_at.is_(None)))


def get_job(session: Session, key: str) -> tuple[ProjectRow, str]:
    """`key` is the numeric project id or the DCREQ (trimmed, uppercased)."""
    stmt = jobs_query()
    if key.isdigit():
        stmt = stmt.where(ProjectRow.id == int(key))
    else:
        norm = normalize_dcreq(key)
        if norm is None:
            raise err(404, "job_not_found", "Job not found")
        stmt = stmt.where(Ref.ref == norm)
    row = session.exec(stmt).first()
    if row is None:
        raise err(404, "job_not_found", "Job not found")
    return row[0], row[1]


def unresolved_total(session: Session, project_id: int) -> int:
    return session.exec(select(func.count()).select_from(Item).where(
        Item.project_id == project_id, Item.status.in_(UNRESOLVED))).one()


# ---- writes ----
def create_job(session: Session, raw_dcreq, name: str | None = None, description: str | None = None,
               site_id: int | None = None) -> ProjectRow:
    dcreq = require_dcreq(raw_dcreq)
    found = find_dcreq(session, dcreq)
    if found is not None:
        raise HTTPException(409, existing_job_detail(session, found))
    who = actor(session)
    now = utcnow()
    cs = new_change_set(session, "api", note=f"job {dcreq} create")
    p = ProjectRow(name=name or dcreq, description=description, site_id=site_id, status="open", opened_at=now,
                   created_by=who, intake_date=now.date())
    session.add(p)
    try:
        session.flush()
        ref = Ref(project_id=p.id, kind="DCREQ", ref=dcreq)
        session.add(ref)
        session.flush()
        p.primary_dcreq_id = ref.id
        # Both files start "not uploaded"; each is auto-resolved when that kind of file is committed (later slices)
        for itype in SKIP_FILE_ITEMS:
            session.add(Item(project_id=p.id, item_type=itype, source="manual", created_by=who,
                             change_set_id=cs.id))
        session.flush()
    except IntegrityError:  # another request created the same DCREQ first
        session.rollback()
        found = find_dcreq(session, dcreq)
        if found is not None:
            raise HTTPException(409, existing_job_detail(session, found)) from None
        raise
    record_audit(session, None, "job.create", "job", p.id, after={
        "dcreq": dcreq, "name": p.name, "status": "open", "opened_at": iso_z(now), "change_set_id": cs.id})
    session.commit()
    session.refresh(p)
    return p


def close_job(session: Session, p: ProjectRow, acknowledge: bool, note: str | None) -> dict | None:
    if p.status == "closed":
        raise err(409, "job_already_closed", "This job is already closed", closed_at=iso_z(p.closed_at))
    n = unresolved_total(session, p.id)
    warning = None
    if n:
        warning = {"code": "job_has_open_items", "message": f"This job still has {n} unresolved "
                   f"item{'s' if n != 1 else ''}.", "unresolved_count": n}
        if not acknowledge:
            raise HTTPException(409, {**warning, "message": warning["message"] + " Close it anyway?"})
    cs = new_change_set(session, "api", note=note or f"job {p.id} close")
    now = utcnow()
    p.status, p.closed_at, p.closed_by = "closed", now, actor(session)
    session.add(p)
    record_audit(session, None, "job.close", "job", p.id, before={"status": "open"}, after={
        "status": "closed", "closed_at": iso_z(now), "unresolved_count": n, "acknowledged_open_items": bool(n),
        "note": note, "change_set_id": cs.id})
    session.commit()
    session.refresh(p)
    return warning


def reopen_job(session: Session, p: ProjectRow, note: str | None) -> None:
    if p.status == "open":
        raise err(409, "job_already_open", "This job is already open")
    before = {"status": "closed", "closed_at": iso_z(p.closed_at), "closed_by": p.closed_by}
    cs = new_change_set(session, "api", note=note or f"job {p.id} reopen")
    p.status, p.closed_at, p.closed_by = "open", None, None  # opened_at is never touched: the clock keeps running
    session.add(p)
    record_audit(session, None, "job.reopen", "job", p.id, before=before, after={
        "status": "open", "opened_at": iso_z(p.opened_at), "note": note, "change_set_id": cs.id})
    session.commit()
    session.refresh(p)
