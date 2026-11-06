"""Items 47/48: operator-only removal of profile-less devices (with audit snapshots) and restore.

Never called from the API, migrations, startup or CI against real data. The CLIs are
scripts/remove_profileless_devices.py and scripts/restore_from_audit.py.
"""
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import delete, or_
from sqlmodel import Session, select

from app.modules.audit.models import AuditEventRow
from app.modules.audit.service import record_audit
from app.modules.connections.models import CableRow, ConnectionRow, DevicePortRow
from app.modules.device_types.models import DeviceTypeProfileRow, DeviceTypeRow
from app.modules.devices.models import DeviceRow
from app.modules.history.models import (
    ChangeSetRow, DeviceNameHistoryRow, DevicePlacementHistoryRow, DeviceStatusHistoryRow,
)
from app.modules.locations.models import HallRow, RackRow, RackRowRow, SiteRow

ACTION = "hard_delete"
SNAPSHOT_VERSION = 1
HISTORY = (("status_history", DeviceStatusHistoryRow), ("placement_history", DevicePlacementHistoryRow),
           ("name_history", DeviceNameHistoryRow))


def verify_admin(engine, email: str, password: str):
    """Items 47/48 (DCIM Security): --actor must be an ACTIVE admin who re-enters their password.
    Uses the normal login check, so failures count toward lockout and are audited (via=script)."""
    from app.modules.auth.models import UserRow
    from app.modules.auth.providers.base import AuthError
    from app.modules.auth.providers.local import LocalProvider
    from app.settings import get_settings
    with Session(engine) as s:
        try:
            LocalProvider(get_settings()).authenticate(s, email, password, via="script")
        except AuthError:
            raise RemovalError("Authentication failed for --actor (wrong password, locked, or not a local user)",
                               exit_code=3)
        user = s.exec(select(UserRow).where(UserRow.email == email.strip().lower())).one()
        if not user.is_active or user.role != "admin":
            raise RemovalError("--actor must be an active admin", exit_code=3)
        s.commit()
        s.refresh(user)
        s.expunge(user)
        return user


def script_meta() -> dict:
    import getpass
    import socket
    try:
        os_user = getpass.getuser()
    except Exception:  # noqa: BLE001
        os_user = None
    return {"via": "script", "os_user": os_user, "host": socket.gethostname()}


class RemovalError(Exception):
    def __init__(self, message: str, exit_code: int = 1, details=None):
        super().__init__(message)
        self.exit_code, self.details = exit_code, details


def _plain(row) -> dict:
    return json.loads(json.dumps(row.model_dump(), default=str))


def select_devices(session: Session, ids: list[int] | None = None, rack_id: int | None = None,
                   lock: bool = False) -> list[DeviceRow]:
    """Every device without a profile: placed, unplaced and soft-deleted."""
    stmt = select(DeviceRow).where(DeviceRow.profile_id.is_(None))
    if ids:
        stmt = stmt.where(DeviceRow.id.in_(ids))
    if rack_id is not None:
        stmt = stmt.where(DeviceRow.rack_id == rack_id)
    if lock and session.get_bind().dialect.name == "postgresql":
        stmt = stmt.with_for_update()
    return list(session.exec(stmt.order_by(DeviceRow.id)).all())


def set_hash(devices: list[DeviceRow]) -> str:
    key = "\n".join(f"{d.id}|{d.host_name}|{d.serial_number}|{d.rack_id}|{d.position_u}|{d.deleted_at}|{d.updated_at}"
                    for d in devices)
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _location(session: Session, d: DeviceRow) -> dict | None:
    if d.rack_id is None:
        return None
    rack = session.get(RackRow, d.rack_id)
    row = session.get(RackRowRow, rack.row_id)
    hall = session.get(HallRow, row.hall_id)
    site = session.get(SiteRow, hall.site_id)
    return {"site": site.name, "hall": hall.name, "row": row.name, "rack": rack.name, "rack_id": rack.id,
            "u": d.position_u, "face": d.face}


def _ports_and_connections(session: Session, device_id: int):
    ports = list(session.exec(select(DevicePortRow).where(DevicePortRow.device_id == device_id)
                              .order_by(DevicePortRow.id)).all())
    pids = [p.id for p in ports]
    conns = list(session.exec(select(ConnectionRow).where(or_(
        ConnectionRow.port1_id.in_(pids), ConnectionRow.port2_id.in_(pids))).order_by(ConnectionRow.id)).all()) \
        if pids else []
    return ports, conns


def report(session: Session, devices: list[DeviceRow]) -> list[dict]:
    out = []
    for d in devices:
        ports, conns = _ports_and_connections(session, d.id)
        t = session.get(DeviceTypeRow, d.device_type_id) if d.device_type_id else None
        counts = {name: len(session.exec(select(m.id).where(m.device_id == d.id)).all()) for name, m in HISTORY}
        out.append({"id": d.id, "host_name": d.host_name, "serial_number": d.serial_number,
                    "location": _location(session, d) or "unplaced", "status": d.status,
                    "device_type": f"{t.manufacturer} {t.name}" if t else None,
                    "deleted_at": str(d.deleted_at) if d.deleted_at else None,
                    "ports": len(ports), "connections": len(conns), **counts, "project_id": d.project_id})
    return out


def snapshot(session: Session, d: DeviceRow, alembic_revision: str | None) -> dict:
    ports, conns = _ports_and_connections(session, d.id)
    connections = []
    for c in conns:
        cable = session.get(CableRow, c.cable_id) if c.cable_id else None
        connections.append({**_plain(c), "cable": _plain(cable) if cable else None, "hops": []})
    return {"snapshot_version": SNAPSHOT_VERSION, "alembic_revision": alembic_revision, "device": _plain(d),
            "placement": _location(session, d),
            **{name: [_plain(r) for r in session.exec(select(m).where(m.device_id == d.id).order_by(m.id)).all()]
               for name, m in HISTORY},
            "ports": [_plain(p) for p in ports], "connections": connections, "epif_ids": [],
            "project_id": d.project_id}


def _revision(session: Session) -> str | None:
    from sqlalchemy import inspect, text
    conn = session.connection()
    if not inspect(conn).has_table("alembic_version"):  # test DBs built with create_all
        return None
    row = conn.execute(text("SELECT version_num FROM alembic_version")).first()
    return row[0] if row else None


def execute(session: Session, *, actor, expect_hash: str, ids=None, rack_id=None,
            include_connections: bool = False, export=None, note: str | None = None) -> dict:
    """One transaction: re-select under lock, hash check, change_set, snapshots, optional export, DELETE.
    The caller commits only when this returns; any exception -> caller rolls back."""
    """`actor` is the UserRow returned by verify_admin()."""
    meta = script_meta()
    devices = select_devices(session, ids, rack_id, lock=True)
    h = set_hash(devices)
    if h != expect_hash:
        raise RemovalError(f"Selection changed since the dry run (hash {h} != {expect_hash}); re-run --dry-run")
    if not devices:
        return {"change_set_id": None, "removed": 0, "hash": h}
    rows = report(session, devices)
    connected = [r for r in rows if r["ports"] or r["connections"]]
    if connected and not include_connections:
        raise RemovalError("Devices with ports/connections need --include-connections", exit_code=2,
                           details=[r["id"] for r in connected])
    cs = ChangeSetRow(source="script", actor=actor.email,
                      note=note or f"remove {len(devices)} profile-less device(s)")
    session.add(cs)
    session.flush()
    rev = _revision(session)
    snaps = []
    for d in devices:
        snap = snapshot(session, d, rev)
        snaps.append(snap)
        record_audit(session, actor, ACTION, "device", d.id, before=snap,
                     after={"change_set_id": cs.id, "reason": "profile-less device removal (item 47)"},
                     via="script", retention_class="restorable")
    exported = export(snaps) if export is not None else None  # before commit; a failure aborts everything
    if exported:
        cs.export_path, cs.export_sha256 = exported["path"], exported["sha256"]
        session.add(cs)
    record_audit(session, actor, "device.remove_profileless", "change_set", cs.id, after={
        "change_set_id": cs.id, "removed": len(devices), "hash": h, "export": exported, **meta}, via="script")
    session.flush()
    dev_ids = [d.id for d in devices]
    port_ids = [p["id"] for s in snaps for p in s["ports"]]
    cable_ids = {c["cable_id"] for s in snaps for c in s["connections"] if c["cable_id"]}
    if port_ids:
        session.exec(delete(ConnectionRow).where(or_(ConnectionRow.port1_id.in_(port_ids),
                                                     ConnectionRow.port2_id.in_(port_ids))))
        if cable_ids:
            still = set(session.exec(select(ConnectionRow.cable_id).where(ConnectionRow.cable_id.in_(cable_ids))).all())
            session.exec(delete(CableRow).where(CableRow.id.in_(cable_ids - still)))
        session.exec(delete(DevicePortRow).where(DevicePortRow.id.in_(port_ids),
                                                 DevicePortRow.rear_port_id.is_not(None)))  # fronts before rears
        session.exec(delete(DevicePortRow).where(DevicePortRow.id.in_(port_ids)))
    for _, m in HISTORY:
        session.exec(delete(m).where(m.device_id.in_(dev_ids)))
    session.exec(delete(DeviceRow).where(DeviceRow.id.in_(dev_ids)))
    session.flush()
    return {"change_set_id": cs.id, "removed": len(dev_ids), "hash": h, "snapshots": snaps}


# ---- item 48: restore ----
def _coerce(model, data: dict) -> dict:
    """JSON snapshot values back to column types (datetimes, dates, decimals)."""
    out = {}
    for k, v in data.items():
        if k not in model.model_fields:
            continue
        col = model.__table__.columns.get(k)
        if v is not None and col is not None:
            try:
                pt = col.type.python_type
            except NotImplementedError:
                pt = None
            if pt is datetime and isinstance(v, str):
                v = datetime.fromisoformat(v)
            elif pt is date and isinstance(v, str):
                v = date.fromisoformat(v)
            elif pt is Decimal and isinstance(v, (str, float, int)):
                v = Decimal(str(v))
        out[k] = v
    return out


def restore(session: Session, *, change_set_id: int, actor, profile_id: int | None = None,
            type_map: dict[int, int] | None = None, ids: list[int] | None = None, dry_run: bool = True) -> dict:
    """Re-insert devices from hard_delete snapshots: unplaced, on a published profile, same ids when free.
    Fails with a list on hostname/serial conflicts or a missing profile mapping (nothing written)."""
    events = [e for e in session.exec(select(AuditEventRow).where(
        AuditEventRow.action == ACTION, AuditEventRow.entity_type == "device").order_by(AuditEventRow.id)).all()
        if json.loads(e.after_json or "{}").get("change_set_id") == change_set_id]
    snaps = [json.loads(e.before_json) for e in events]
    if ids:
        snaps = [s for s in snaps if s["device"]["id"] in ids]
    if not snaps:
        raise RemovalError(f"No hard_delete snapshots for change_set {change_set_id}")
    from app.modules.history.models import RestoredDeviceRow
    already = list(session.exec(select(RestoredDeviceRow.original_device_id).where(
        RestoredDeviceRow.source_change_set_id == change_set_id)).all())
    snaps = [s for s in snaps if s["device"]["id"] not in already]
    if already and not snaps:  # D46: idempotent, a second restore creates nothing
        raise RemovalError(f"change_set {change_set_id} is already restored (devices {sorted(already)})",
                           details=sorted(already))
    from sqlalchemy import func as sa_func
    problems, plan = [], []
    for s in snaps:
        d = s["device"]
        target = (type_map or {}).get(d.get("device_type_id")) or profile_id
        prof = session.get(DeviceTypeProfileRow, target) if target else None
        if prof is None or prof.status != "published":
            problems.append({"id": d["id"], "host_name": d["host_name"], "problem": "no published profile mapping"
                             + (f" (profile {target} is {prof.status})" if prof else "")})
            continue
        if d.get("serial_number") and session.exec(select(DeviceRow.id).where(
                DeviceRow.serial_number == d["serial_number"])).first():
            problems.append({"id": d["id"], "host_name": d["host_name"], "problem": "serial_number in use"})
            continue
        # D1 host_name per rack. Devices come back unplaced, so this checks the snapshot's rack (if it
        # still exists) so a later re-placement can't collide, plus live unplaced devices with that name.
        old_rack = (s.get("placement") or {}).get("rack_id")
        clash = session.exec(select(DeviceRow.id).where(
            sa_func.lower(DeviceRow.host_name) == d["host_name"].lower(), DeviceRow.deleted_at.is_(None),
            or_(DeviceRow.rack_id.is_(None), DeviceRow.rack_id == old_rack) if old_rack else
            DeviceRow.rack_id.is_(None))).first()
        if clash:
            problems.append({"id": d["id"], "host_name": d["host_name"], "problem": "host_name in use",
                             "device_id": clash})
            continue
        plan.append((s, prof))
    if problems:
        raise RemovalError("Restore refused; nothing written", details=problems)
    result = {"restored": [], "dry_run": dry_run}
    if dry_run:
        result["restored"] = [{"old_id": s["device"]["id"], "host_name": s["device"]["host_name"],
                               "profile_id": p.id} for s, p in plan]
        return result
    meta = script_meta()
    cs = ChangeSetRow(source="script", actor=actor.email, note=f"restore from change_set {change_set_id}")
    from app.modules.history.models import RestoredDeviceRow
    session.add(cs)
    session.flush()
    port_map: dict[int, int] = {}
    for s, prof in plan:
        d = dict(s["device"])
        old_id = d["id"]
        where = s.get("placement")
        loc = (f"Restored from change_set {change_set_id}; was "
               + (f"{where['site']}/{where['hall']}/{where['row']}/{where['rack']} U{where['u']} {where['face']}"
                  if where else "unplaced"))
        d.update(rack_id=None, position_u=None, profile_id=prof.id, device_type_id=prof.device_type_id,
                 needs_review=False, needs_review_reason=None, notes="\n".join(filter(None, [d.get("notes"), loc])))
        if session.get(DeviceRow, old_id) is not None:
            d.pop("id")
        dev = DeviceRow(**_coerce(DeviceRow, d))
        session.add(dev)
        session.flush()
        for name, m in HISTORY:
            for h in s[name]:
                h = dict(h)
                h.pop("id", None)
                h["device_id"] = dev.id
                session.add(m(**_coerce(m, h)))
        for p in sorted(s["ports"], key=lambda p: p.get("rear_port_id") is not None):
            p = dict(p)
            old_pid = p.pop("id")
            p["device_id"] = dev.id
            if p.get("rear_port_id"):
                p["rear_port_id"] = port_map.get(p["rear_port_id"])
            port = DevicePortRow(**_coerce(DevicePortRow, p))
            session.add(port)
            session.flush()
            port_map[old_pid] = port.id
        result["restored"].append({"old_id": old_id, "new_id": dev.id, "host_name": dev.host_name,
                                   "profile_id": prof.id})
        session.add(RestoredDeviceRow(source_change_set_id=change_set_id, original_device_id=old_id,
                                      restored_device_id=dev.id, restore_change_set_id=cs.id))
        record_audit(session, actor, "insert", "device", dev.id, after={
            "change_set_id": cs.id, "restored_from_change_set_id": change_set_id, "old_id": old_id, **meta},
            via="script")
    # connections whose both ports exist again (other end restored too, or never removed)
    seen = set()
    for s, _ in plan:
        for c in s["connections"]:
            if c["id"] in seen:
                continue
            seen.add(c["id"])
            a, b = port_map.get(c["port1_id"], c["port1_id"]), port_map.get(c["port2_id"], c["port2_id"])
            if session.get(DevicePortRow, a) is None or session.get(DevicePortRow, b) is None:
                continue
            cable_id = None
            if c.get("cable"):
                cab = dict(c["cable"])
                cab.pop("id", None)
                cable = CableRow(**_coerce(CableRow, cab))
                session.add(cable)
                session.flush()
                cable_id = cable.id
            lo, hi = sorted((a, b))
            conn = {k: v for k, v in c.items() if k not in ("id", "cable", "hops", "cable_id", "port1_id", "port2_id")}
            session.add(ConnectionRow(**_coerce(ConnectionRow, conn), port1_id=lo, port2_id=hi, cable_id=cable_id))
    session.flush()
    result["change_set_id"] = cs.id
    return result
