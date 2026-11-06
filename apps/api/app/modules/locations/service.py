from fastapi import HTTPException
from sqlmodel import Session, SQLModel, func, select

from app.db import commit_or_409


# Helper: fetch a row by id or raise a 404 ("Site not found", ...)
def get_or_404(session: Session, model: type[SQLModel], obj_id: int, label: str):
    obj = session.get(model, obj_id)
    if obj is None or getattr(obj, "deleted_at", None) is not None:  # soft-deleted = gone
        raise HTTPException(status_code=404, detail=f"{label} not found")
    return obj


# Helper: refuse to delete a parent that still has children
def ensure_no_children(session: Session, child_model, fk_column, parent_id: int, message: str):
    statement = select(func.count()).select_from(child_model).where(fk_column == parent_id)
    if hasattr(child_model, "deleted_at"):
        statement = statement.where(child_model.deleted_at.is_(None))
    count = session.exec(statement).one()
    if count:
        raise HTTPException(status_code=409, detail=message)


# Helper: save a new/changed row, mapping unique-name clashes to a 409
def save(session: Session, obj, conflict_message: str):
    session.add(obj)
    commit_or_409(session, conflict_message)
    session.refresh(obj)
    return obj


# D6: the default site (created on first use if no site is flagged, e.g. a fresh test DB)
def default_site(session: Session):
    from app.modules.locations.models import SiteRow

    site = session.exec(select(SiteRow).where(SiteRow.is_default)).first()
    if site is None:
        site = session.exec(select(SiteRow).where(SiteRow.name == "Default")).first() or SiteRow(name="Default")
        site.is_default = True
        session.add(site)
        session.flush()
    return site


# Move the default flag to `site` (unset the old one first so the partial unique index holds)
def make_default(session: Session, site) -> None:
    from app.modules.locations.models import SiteRow

    for other in session.exec(select(SiteRow).where(SiteRow.is_default, SiteRow.id != site.id)).all():
        other.is_default = False
        session.add(other)
    session.flush()
    site.is_default = True


# Query-string aliases: ?building_id= / ?room_id= (422 when both forms disagree)
def alias_param(canonical_name: str, canonical, alias_name: str, alias):
    if canonical is not None and alias is not None and canonical != alias:
        raise HTTPException(status_code=422, detail=f"{canonical_name} and {alias_name} disagree")
    return canonical if canonical is not None else alias
