from datetime import datetime

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db import get_session
from app.modules.audit.models import AuditEventRow
from app.modules.auth.deps import ADMIN
from app.pagination import Pagination, paginate

router = APIRouter(prefix="/audit-events", tags=["audit"], dependencies=[Depends(ADMIN)])


class AuditEvent(BaseModel):
    id: int
    occurred_at: datetime
    actor_user_id: int | None
    actor_ip: str | None
    request_id: str | None
    action: str
    entity_type: str
    entity_id: int | None
    before_json: str | None
    after_json: str | None
    import_batch_id: str | None
    via: str | None = None
    retention_class: str = "standard"


# Admin-only, newest first
@router.get("", response_model=list[AuditEvent])
def list_audit_events(
    response: Response,
    entity_type: str | None = Query(None),
    entity_id: int | None = Query(None),
    action: str | None = Query(None),
    actor_user_id: int | None = Query(None),
    page: Pagination = Depends(),
    session: Session = Depends(get_session),
):
    statement = select(AuditEventRow)
    for column, value in [(AuditEventRow.entity_type, entity_type), (AuditEventRow.entity_id, entity_id),
                          (AuditEventRow.action, action), (AuditEventRow.actor_user_id, actor_user_id)]:
        if value is not None:
            statement = statement.where(column == value)
    return paginate(session, statement, page, response, AuditEventRow.id.desc())
