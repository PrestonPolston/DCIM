from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import or_
from sqlmodel import Session, func, select

from app.db import flush_or_409, get_session
from app.modules.audit.service import record_audit
from app.modules.auth.deps import TECH, get_current_user
from app.modules.connections import service as svc
from app.modules.connections.models import ConnectionRow, DevicePortRow
from app.modules.connections.schemas import (
    CableType, Connection, ConnectionCreate, ConnectionUpdate, DeviceConnection, Port, PortCreate,
)
from app.modules.devices.service import find_device
from app.modules.locations.service import alias_param
from app.pagination import Pagination

router = APIRouter(dependencies=[Depends(get_current_user)], tags=["connections"])
LABEL_TAKEN = {"code": "cable_label_conflict", "message": "Another live cable already has this label"}
Derived = Literal["install", "active", "decom"]


# ---- ports ----
@router.get("/devices/{device_id}/ports", response_model=list[Port])
def list_ports(device_id: int, session: Session = Depends(get_session)):
    find_device(session, device_id)
    ports = session.exec(select(DevicePortRow).where(DevicePortRow.device_id == device_id,
                                                     DevicePortRow.deleted_at.is_(None))
                         .order_by(DevicePortRow.slot, DevicePortRow.name, DevicePortRow.id)).all()
    ids = [p.id for p in ports]
    used = {}
    if ids:
        for c in session.exec(select(ConnectionRow).where(or_(ConnectionRow.port1_id.in_(ids),
                                                              ConnectionRow.port2_id.in_(ids)))).all():
            used[c.port1_id] = used[c.port2_id] = c.id
    return [Port(**p.model_dump(), connection_id=used.get(p.id)) for p in ports]


@router.post("/devices/{device_id}/ports", response_model=Port, status_code=201, dependencies=[Depends(TECH)])
def create_port(device_id: int, payload: PortCreate, session: Session = Depends(get_session)):
    find_device(session, device_id)
    port = DevicePortRow(device_id=device_id, **payload.model_dump())
    session.add(port)
    flush_or_409(session, {"code": "port_name_conflict", "message": "This device already has a port with that name"})
    session.commit()
    session.refresh(port)
    return Port(**port.model_dump())


# ---- connections ----
@router.get("/devices/{device_id}/connections", response_model=list[DeviceConnection])
def device_connections(device_id: int, session: Session = Depends(get_session)):
    find_device(session, device_id)
    rows = session.exec(svc.apply_filters(svc.base_query(), device_id=device_id).order_by(ConnectionRow.id)).all()
    return [svc.device_connection_out(r, device_id) for r in rows]


class ConnectionFilters:
    def __init__(
        self,
        hall_id: int | None = Query(None, description="Either end in this hall"),
        room_id: int | None = Query(None, description="Alias of hall_id"),
        row_id: int | None = Query(None),
        rack_id: list[int] | None = Query(None, description="Either end in any of these cabinets (repeatable)"),
        device_id: int | None = Query(None, description="Either end is this device"),
        cable_type: list[CableType] | None = Query(None),
        derived_status: list[Derived] | None = Query(None, description="Server-side derived status filter"),
        cross_cabinet: bool | None = Query(None, description="true = ends in different cabinets"),
        q: str | None = Query(None, max_length=100, description="Host name, port name or cable label"),
    ):
        self.kw = dict(hall_id=alias_param("hall_id", hall_id, "room_id", room_id), row_id=row_id, rack_id=rack_id, device_id=device_id, cable_type=cable_type,
                       derived_status=derived_status, cross_cabinet=cross_cabinet, q=q)

    def query(self):
        return svc.apply_filters(svc.base_query(), **self.kw)


@router.get("/connections", response_model=list[Connection])
def list_connections(response: Response, filters: ConnectionFilters = Depends(), page: Pagination = Depends(),
                     session: Session = Depends(get_session)):
    stmt = filters.query()
    total = session.exec(select(func.count()).select_from(stmt.with_only_columns(ConnectionRow.id, maintain_column_froms=True).subquery())).one()
    response.headers["X-Total-Count"] = str(total)
    rows = session.exec(stmt.order_by(ConnectionRow.id).offset(page.offset).limit(page.limit)).all()
    return [svc.connection_out(r) for r in rows]


@router.get("/connections/export", response_class=Response, responses={200: {"content": {"text/csv": {}}}})
def export_connections(filters: ConnectionFilters = Depends(), session: Session = Depends(get_session)):
    rows = session.exec(filters.query().order_by(ConnectionRow.id)).all()
    return Response(svc.export_csv(rows), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="connections.csv"'})


@router.get("/connections/{connection_id}", response_model=Connection)
def get_connection(connection_id: int, session: Session = Depends(get_session)):
    return svc.load_connection(session, connection_id)


@router.post("/connections", response_model=Connection, status_code=201, dependencies=[Depends(TECH)])
def create_connection(payload: ConnectionCreate, session: Session = Depends(get_session)):
    da = svc.live_device(session, payload.a_device_id)
    db = svc.live_device(session, payload.b_device_id)
    pa = svc.resolve_port(session, da, payload.a_port_id, payload.a_port_name)
    pb = svc.resolve_port(session, db, payload.b_port_id, payload.b_port_name)
    if pa.id == pb.id:
        raise HTTPException(422, {"code": "self_connection", "message": "A port can't be connected to itself"})
    svc.lock_ports(session, [pa.id, pb.id])
    for port, dev in ((pa, da), (pb, db)):
        other = svc.port_in_use(session, port.id)
        if other is not None:
            session.rollback()
            raise svc.busy(port, dev, other)
    p1, p2 = sorted((pa.id, pb.id))  # canonical order (item 11 Q14); a/b in responses = port1/port2
    conn = ConnectionRow(port1_id=p1, port2_id=p2)
    session.add(conn)
    svc.apply_cable(session, conn, payload.model_dump(exclude_unset=True))
    flush_or_409(session, {"code": "connection_conflict",
                           "message": "A port is already connected or the cable label is taken"})
    out = svc.load_connection(session, conn.id)
    record_audit(session, None, "connection.create", "connection", conn.id, after=_audit_view(out))
    session.commit()
    return out


@router.patch("/connections/{connection_id}", response_model=Connection, dependencies=[Depends(TECH)])
def update_connection(connection_id: int, payload: ConnectionUpdate, session: Session = Depends(get_session)):
    conn = session.get(ConnectionRow, connection_id)
    if conn is None:
        raise HTTPException(404, "Connection not found")
    before = _audit_view(svc.load_connection(session, connection_id))
    svc.apply_cable(session, conn, payload.model_dump(exclude_unset=True))
    flush_or_409(session, LABEL_TAKEN)
    out = svc.load_connection(session, connection_id)
    record_audit(session, None, "connection.update", "connection", conn.id, before=before, after=_audit_view(out))
    session.commit()
    return out


@router.delete("/connections/{connection_id}", status_code=204, dependencies=[Depends(TECH)])
def delete_connection(connection_id: int, session: Session = Depends(get_session)):
    conn = session.get(ConnectionRow, connection_id)
    if conn is None:
        raise HTTPException(404, "Connection not found")
    before = _audit_view(svc.load_connection(session, connection_id))
    cable_id = conn.cable_id
    session.delete(conn)
    session.flush()
    svc.drop_cable(session, cable_id)
    record_audit(session, None, "connection.delete", "connection", connection_id, before=before)
    session.commit()
    return Response(status_code=204)


def _audit_view(out: dict) -> dict:
    cable = out["cable"] or {}
    return {"a": f"{out['a']['host_name']}:{out['a']['port_name']}", "b": f"{out['b']['host_name']}:{out['b']['port_name']}",
            "a_port_id": out["a"]["port_id"], "b_port_id": out["b"]["port_id"],
            "cable": {k: (str(v) if v is not None else None) for k, v in cable.items()}, "notes": out["notes"]}
