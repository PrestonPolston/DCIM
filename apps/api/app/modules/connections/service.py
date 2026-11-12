import csv
import io

from fastapi import HTTPException
from sqlalchemy import and_, case, func, or_
from sqlalchemy.orm import aliased
from sqlmodel import Session, select

from app.db import flush_or_409
from app.modules.connections.models import CableRow, ConnectionRow, DevicePortRow
from app.modules.devices.csv_io import neutralize
from app.modules.devices.models import DeviceRow
from app.modules.locations.models import HallRow, RackRow, RackRowRow
from app.pagination import contains

P1, P2 = aliased(DevicePortRow), aliased(DevicePortRow)
D1, D2 = aliased(DeviceRow), aliased(DeviceRow)
R1, R2 = aliased(RackRow), aliased(RackRow)
W1, W2 = aliased(RackRowRow), aliased(RackRowRow)
H1, H2 = aliased(HallRow), aliased(HallRow)


def derive_status(a: str, b: str) -> str:
    """Design rule: either end decom -> decom; else either end install -> install; else active."""
    if "decom" in (a, b):
        return "decom"
    return "install" if "install" in (a, b) else "active"


def derived_status_sql():
    return case((or_(D1.status == "decom", D2.status == "decom"), "decom"),
                (or_(D1.status == "install", D2.status == "install"), "install"), else_="active")


def base_query():
    """connections joined to both ends (port, device, cabinet, row, hall) and the cable."""
    return (select(ConnectionRow, P1, D1, R1, W1, H1, P2, D2, R2, W2, H2, CableRow)
            .join(P1, P1.id == ConnectionRow.port1_id).join(D1, D1.id == P1.device_id)
            .outerjoin(R1, R1.id == D1.rack_id).outerjoin(W1, W1.id == R1.row_id).outerjoin(H1, H1.id == W1.hall_id)
            .join(P2, P2.id == ConnectionRow.port2_id).join(D2, D2.id == P2.device_id)
            .outerjoin(R2, R2.id == D2.rack_id).outerjoin(W2, W2.id == R2.row_id).outerjoin(H2, H2.id == W2.hall_id)
            .outerjoin(CableRow, CableRow.id == ConnectionRow.cable_id))


def apply_filters(stmt, *, hall_id=None, row_id=None, rack_id=None, device_id=None, cable_type=None, q=None,
                  derived_status=None, cross_cabinet=None):
    def either(c1, c2):
        return or_(c1, c2)

    if hall_id is not None:
        stmt = stmt.where(either(H1.id == hall_id, H2.id == hall_id))
    if row_id is not None:
        stmt = stmt.where(either(W1.id == row_id, W2.id == row_id))
    if rack_id:
        stmt = stmt.where(either(R1.id.in_(rack_id), R2.id.in_(rack_id)))
    if device_id is not None:
        stmt = stmt.where(either(D1.id == device_id, D2.id == device_id))
    if cable_type:
        stmt = stmt.where(CableRow.cable_type.in_(cable_type))
    if q:
        stmt = stmt.where(or_(contains(D1.host_name, q), contains(D2.host_name, q), contains(P1.name, q),
                              contains(P2.name, q), contains(CableRow.label, q)))
    if derived_status:
        stmt = stmt.where(derived_status_sql().in_(derived_status))
    if cross_cabinet is True:
        stmt = stmt.where(or_(D1.rack_id.is_(None), D2.rack_id.is_(None), D1.rack_id != D2.rack_id))
    return stmt


def _end(p, d, r, w, h) -> dict:
    return {"device_id": d.id, "host_name": d.host_name, "status": d.status, "rack_id": d.rack_id,
            "cabinet": r.name if r else None, "hall_id": h.id if h else None, "hall": h.name if h else None,
            "row": w.name if w else None, "position_u": d.position_u, "face": d.face if d.rack_id else None,
            "port_id": p.id, "port_name": p.name, "slot": p.slot}


def _cable(c):
    if c is None:
        return None
    return {"id": c.id, "cable_type": c.cable_type, "label": c.label, "color": c.color, "length_m": c.length_m}


def connection_out(row) -> dict:
    conn, p1, d1, r1, w1, h1, p2, d2, r2, w2, h2, cable = row
    return {"id": conn.id, "a": _end(p1, d1, r1, w1, h1), "b": _end(p2, d2, r2, w2, h2), "cable": _cable(cable),
            "derived_status": derive_status(d1.status, d2.status), "notes": conn.notes,
            "created_at": conn.created_at}


def load_connection(session: Session, connection_id: int) -> dict:
    row = session.exec(base_query().where(ConnectionRow.id == connection_id)).first()
    if row is None:
        raise HTTPException(404, "Connection not found")
    return connection_out(row)


def device_connection_out(row, device_id: int) -> dict:
    out = connection_out(row)
    local, far = (out["a"], out["b"]) if out["a"]["device_id"] == device_id else (out["b"], out["a"])
    return {
        "connection_id": out["id"],
        "local_port": {"id": local["port_id"], "name": local["port_name"], "slot": local["slot"]},
        "far_device": {"id": far["device_id"], "host_name": far["host_name"], "rack_id": far["rack_id"],
                       "cabinet": far["cabinet"], "hall": far["hall"], "position_u": far["position_u"],
                       "face": far["face"], "status": far["status"]},
        "far_port": {"id": far["port_id"], "name": far["port_name"], "slot": far["slot"]},
        "cable": out["cable"], "local_status": local["status"], "far_status": far["status"],
        "derived_status": out["derived_status"], "notes": out["notes"],
    }


# ---- writes ----
def live_device(session: Session, device_id: int) -> DeviceRow:
    d = session.get(DeviceRow, device_id)
    if d is None or d.deleted_at is not None:
        raise HTTPException(404, f"Device {device_id} not found")
    return d


def find_port_by_name(session: Session, device_id: int, name: str, slot: str | None = None):
    return session.exec(select(DevicePortRow).where(
        DevicePortRow.device_id == device_id, DevicePortRow.deleted_at.is_(None),
        func.lower(DevicePortRow.name) == name.lower(),
        func.coalesce(DevicePortRow.slot, "") == (slot or ""))).first()


def resolve_port(session: Session, device: DeviceRow, port_id: int | None, port_name: str | None) -> DevicePortRow:
    if port_id is not None:
        port = session.get(DevicePortRow, port_id)
        if port is None or port.deleted_at is not None or port.device_id != device.id:
            raise HTTPException(404, f"Port {port_id} not found on device {device.id}")
    else:
        port = find_port_by_name(session, device.id, port_name)
        if port is None:  # quick entry: create the port on the fly
            port = DevicePortRow(device_id=device.id, name=port_name)
            session.add(port)
            session.flush()
    if port.role != "endpoint":
        raise HTTPException(422, "Only endpoint ports can be connected (panel paths are not supported yet)")
    return port


def lock_ports(session: Session, ids: list[int]) -> None:
    """Serialize writers on these ports (PG row locks; SQLite already serializes writers)."""
    if session.get_bind().dialect.name == "postgresql":
        session.exec(select(DevicePortRow.id).where(DevicePortRow.id.in_(ids)).with_for_update()).all()


def port_in_use(session: Session, port_id: int, lane: int = 0, exclude: int | None = None,
                breakout: bool = False):
    """The non-removed connection holding (port, lane), checked across both columns (DEVICE_DATA_MODEL §7).
    breakout=True also treats lane 0 vs lane N on the same port as a clash (whole port vs one lane)."""
    if breakout:
        lanes = [0] if lane == 0 else [lane, 0]
        if lane == 0:  # whole port: any lane in use blocks it
            hit = or_(ConnectionRow.port1_id == port_id, ConnectionRow.port2_id == port_id)
        else:
            hit = or_(and_(ConnectionRow.port1_id == port_id, ConnectionRow.port1_lane.in_(lanes)),
                      and_(ConnectionRow.port2_id == port_id, ConnectionRow.port2_lane.in_(lanes)))
    else:
        hit = or_(and_(ConnectionRow.port1_id == port_id, ConnectionRow.port1_lane == lane),
                  and_(ConnectionRow.port2_id == port_id, ConnectionRow.port2_lane == lane))
    stmt = select(ConnectionRow.id).where(hit, ConnectionRow.status != "removed")
    if exclude is not None:
        stmt = stmt.where(ConnectionRow.id != exclude)
    return session.exec(stmt).first()


def busy(port: DevicePortRow, device: DeviceRow, other: int) -> HTTPException:
    return HTTPException(409, {"code": "port_in_use",
                               "message": f"Port {port.name} on {device.host_name} already has a connection",
                               "connection_id": other})


def apply_cable(session: Session, conn: ConnectionRow, fields: dict) -> None:
    keys = {"cable_type": "cable_type", "cable_label": "label", "cable_color": "color",
            "cable_length_m": "length_m"}
    cable_changes = {keys[k]: v for k, v in fields.items() if k in keys}
    if "notes" in fields:
        conn.notes = fields["notes"]
    if not cable_changes:
        return
    cable = session.get(CableRow, conn.cable_id) if conn.cable_id else None
    if cable is None:
        cable = CableRow()
        session.add(cable)
    for k, v in cable_changes.items():
        setattr(cable, k, v)
    flush_or_409(session, {"code": "cable_label_conflict", "message": "Another live cable already has this label"})
    conn.cable_id = cable.id


def drop_cable(session: Session, cable_id: int | None) -> None:
    """v1: one cable per connection and no cable status, so the cable goes with its connection."""
    cable = session.get(CableRow, cable_id) if cable_id else None
    if cable is not None and session.exec(select(ConnectionRow.id).where(ConnectionRow.cable_id == cable.id)).first() is None:
        session.delete(cable)


# ---- CSV ----
EXPORT_COLUMNS = [
    "id", "a_device_id", "a_host_name", "a_port", "a_hall", "a_row", "a_cabinet", "a_ru", "a_face",
    "b_device_id", "b_host_name", "b_port", "b_hall", "b_row", "b_cabinet", "b_ru", "b_face",
    "cable_label", "cable_type", "cable_color", "cable_length_m", "a_status", "b_status", "derived_status", "notes",
]


def export_csv(rows) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=EXPORT_COLUMNS)
    w.writeheader()
    for row in rows:
        c = connection_out(row)
        line = {"id": c["id"], "derived_status": c["derived_status"], "notes": c["notes"]}
        for side in ("a", "b"):
            e = c[side]
            line.update({f"{side}_device_id": e["device_id"], f"{side}_host_name": e["host_name"],
                         f"{side}_port": f"{e['slot']}/{e['port_name']}" if e["slot"] else e["port_name"],
                         f"{side}_hall": e["hall"], f"{side}_row": e["row"], f"{side}_cabinet": e["cabinet"],
                         f"{side}_ru": e["position_u"], f"{side}_face": e["face"], f"{side}_status": e["status"]})
        cab = c["cable"] or {}
        line.update({"cable_label": cab.get("label"), "cable_type": cab.get("cable_type"),
                     "cable_color": cab.get("color"), "cable_length_m": cab.get("length_m")})
        w.writerow({k: neutralize(v) for k, v in line.items()})
    return buf.getvalue()

