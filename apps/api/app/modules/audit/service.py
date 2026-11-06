from app.security.client_ip import client_ip
import json

from sqlmodel import Session

from app.modules.audit.models import AuditEventRow


def _dump(data) -> str | None:
    return None if data is None else json.dumps(data, default=str, sort_keys=True)


# Append an audit event in the caller's transaction (committed together with the change)
def record_audit(
    session: Session, actor, action: str, entity_type: str, entity_id: int | None,
    before: dict | None = None, after: dict | None = None,
    ip: str | None = None, request_id: str | None = None, import_batch_id: str | None = None,
    via: str | None = None, retention_class: str = "standard",
) -> None:
    meta = session.info.get("request_meta", {})
    actor = actor if actor is not None else session.info.get("user")
    session.add(AuditEventRow(
        actor_user_id=getattr(actor, "id", None), actor_ip=ip or meta.get("ip"),
        request_id=request_id or meta.get("request_id"),
        action=action, entity_type=entity_type, entity_id=entity_id,
        before_json=_dump(before), after_json=_dump(after), import_batch_id=import_batch_id,
        via=via, retention_class=retention_class,
    ))


# Only the fields that changed: ({field: old}, {field: new})
def diff(before: dict, after: dict) -> tuple[dict, dict]:
    keys = [k for k in after if before.get(k) != after.get(k)]
    return {k: before.get(k) for k in keys}, {k: after.get(k) for k in keys}


# Convenience for routers: actor, IP and request id come from the request
def audit(request, session: Session, action: str, entity_type: str, entity_id: int | None,
          before: dict | None = None, after: dict | None = None, import_batch_id: str | None = None) -> None:
    record_audit(
        session, getattr(request.state, "user", None), action, entity_type, entity_id, before, after,
        ip=client_ip(request),
        request_id=getattr(request.state, "request_id", None), import_batch_id=import_batch_id,
    )
