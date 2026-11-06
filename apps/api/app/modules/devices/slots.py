"""P1-10 / DESIGN §2.4: device_ru_slots, one row per (rack, U, side) a device blocks.

The PK (rack_id, u, side) makes overlapping placements impossible at the DB level on SQLite and Postgres.
Rows are derived, never written by hand: a session after_flush hook rewrites the slots of every device whose
rack_id / position_u / face / profile_id changed (or that was inserted/deleted) in the same transaction, so
every write path (API, CSV import, adopt, decom, rack delete, scripts, seed) stays in sync. Same rule as the
Python overlap check: every device with rack_id set occupies position_u .. position_u+u_height-1 of its
profile; full-depth blocks both sides, otherwise only its face; 0 U blocks nothing.

LIMITS (DB Architect review of p1_23):
- Placement writes must stay ORM-only (load DeviceRow, set attributes, flush). Core/bulk statements
  (`update(DeviceRow)...`, `session.execute(insert(...))`, raw `UPDATE devices SET rack_id=...`) bypass the hook
  and leave the slots stale. tests/test_ru_slots.py::test_guard_no_bulk_placement_writes fails on such code.
- The DB does not check rack height (position_u + u_height - 1 <= racks.u_height spans tables); that stays in
  the Python fit check (validate_placement). Slots only guarantee no two devices hold the same (rack, U, side).
- A slot clash at commit is mapped to 409 {code: "ru_slot_taken"} by commit_or_409 / flush_or_409.
"""
from sqlalchemy import CheckConstraint, delete, event, insert, inspect, select
from sqlmodel import Field, Session, SQLModel

from app.modules.device_types.models import DeviceTypeProfileRow
from app.modules.devices.models import DeviceRow

WATCHED = ("rack_id", "position_u", "face", "profile_id")


class DeviceRuSlotRow(SQLModel, table=True):
    __tablename__ = "device_ru_slots"
    __table_args__ = (
        CheckConstraint("side IN ('front','rear')", name="side"),
        CheckConstraint("u >= 1", name="u"),
    )

    rack_id: int = Field(foreign_key="racks.id", ondelete="CASCADE", primary_key=True)
    u: int = Field(primary_key=True)
    side: str = Field(max_length=5, primary_key=True)
    device_id: int = Field(foreign_key="devices.id", ondelete="CASCADE", index=True)


def slot_rows(device_id, rack_id, position_u, face, u_height, full_depth) -> list[dict]:
    if rack_id is None or position_u is None or not u_height:
        return []
    sides = ("front", "rear") if full_depth else (face or "front",)
    return [{"rack_id": rack_id, "u": u, "side": s, "device_id": device_id}
            for u in range(position_u, position_u + u_height) for s in sides]


def _changed(obj) -> bool:
    st = inspect(obj)
    return any(st.attrs[k].history.has_changes() for k in WATCHED)


@event.listens_for(Session, "before_flush")
def _collect(session, _ctx, _instances):
    from app.modules.locations.models import RackRow, RackRowRow
    pending = session.info.setdefault("_slot_devices", {})
    for obj in session.new:
        if isinstance(obj, DeviceRow):
            pending[id(obj)] = obj
        elif isinstance(obj, RackRow) and obj.hall_id is None and obj.row_id is not None:
            row = session.get(RackRowRow, obj.row_id)
            if row is not None:
                obj.hall_id = row.hall_id
    for obj in session.dirty:
        if isinstance(obj, DeviceRow) and _changed(obj):
            pending[id(obj)] = obj


@event.listens_for(Session, "after_flush")
def _sync(session, _ctx):
    pending = session.info.pop("_slot_devices", {})
    gone = [o.id for o in session.deleted if isinstance(o, DeviceRow) and o.id is not None]
    devices = [d for d in pending.values() if d.id is not None and d not in session.deleted]
    if not devices and not gone:
        return
    conn = session.connection()
    ids = [d.id for d in devices] + gone
    conn.execute(delete(DeviceRuSlotRow).where(DeviceRuSlotRow.device_id.in_(ids)))
    pids = {d.profile_id for d in devices if d.rack_id is not None and d.profile_id is not None}
    fit = {}
    if pids:
        fit = {pid: (h, fd) for pid, h, fd in conn.execute(select(
            DeviceTypeProfileRow.id, DeviceTypeProfileRow.u_height, DeviceTypeProfileRow.is_full_depth)
            .where(DeviceTypeProfileRow.id.in_(pids))).all()}
    rows = []
    for d in devices:
        h, fd = fit.get(d.profile_id, (1, True))  # unknown profile: 1 U, both sides (legacy occupant rule)
        rows += slot_rows(d.id, d.rack_id, d.position_u, d.face, h, fd)
    if rows:
        conn.execute(insert(DeviceRuSlotRow), rows)
