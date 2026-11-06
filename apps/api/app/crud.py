"""Small generic CRUD router for simple reference tables (groups, vendors, contacts, projects)."""
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, or_, select

from app.db import commit_or_409, get_session
from app.modules.auth.deps import ADMIN, TECH
from app.modules.locations.service import get_or_404
from app.pagination import Pagination, contains, paginate


def crud_router(router: APIRouter, path: str, row, create, update, out, label: str, conflict: str,
                search: list, before_save: Callable | None = None, in_use: Callable | None = None) -> None:
    @router.get(path, response_model=list[out], name=f"list_{label}")
    def list_items(response: Response, q: str | None = Query(None, max_length=100),
                   page: Pagination = Depends(), session: Session = Depends(get_session)):
        statement = select(row)
        if hasattr(row, "deleted_at"):
            statement = statement.where(row.deleted_at.is_(None))
        if q:
            statement = statement.where(or_(*[contains(c, q) for c in search]))
        return paginate(session, statement, page, response, row.id)

    @router.post(path, response_model=out, status_code=201, dependencies=[Depends(TECH)], name=f"create_{label}")
    def create_item(payload: create, session: Session = Depends(get_session)):
        obj = row(**payload.model_dump())
        if before_save:
            before_save(session, obj)
        session.add(obj)
        commit_or_409(session, conflict)
        session.refresh(obj)
        return obj

    @router.get(path + "/{item_id}", response_model=out, name=f"get_{label}")
    def get_item(item_id: int, session: Session = Depends(get_session)):
        return get_or_404(session, row, item_id, label)

    @router.patch(path + "/{item_id}", response_model=out, dependencies=[Depends(TECH)], name=f"update_{label}")
    def update_item(item_id: int, payload: update, session: Session = Depends(get_session)):
        obj = get_or_404(session, row, item_id, label)
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(obj, key, value)
        if before_save:
            before_save(session, obj)
        commit_or_409(session, conflict)
        session.refresh(obj)
        return obj

    @router.delete(path + "/{item_id}", status_code=204, dependencies=[Depends(ADMIN)], name=f"delete_{label}")
    def delete_item(item_id: int, session: Session = Depends(get_session)):
        obj = get_or_404(session, row, item_id, label)
        if in_use and in_use(session, obj):
            raise HTTPException(status_code=409, detail=f"{label} is still in use")
        if hasattr(obj, "deleted_at"):  # soft delete (e.g. projects keep their history)
            from app.timestamps import utcnow
            obj.deleted_at = utcnow()
            session.commit()
            return Response(status_code=204)
        session.delete(obj)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            raise HTTPException(status_code=409, detail=f"{label} is still referenced")
        return Response(status_code=204)
