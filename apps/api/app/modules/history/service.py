from sqlmodel import Session

from app.modules.history.models import (
    ChangeSetRow, DeviceNameHistoryRow, DevicePlacementHistoryRow, DeviceStatusHistoryRow,
)


# Start a change set (one per request/import); flushed so rows can reference it
def new_change_set(session: Session, source: str, actor: str | None = None, note: str | None = None) -> ChangeSetRow:
    if actor is None and session.info.get("user") is not None:
        actor = session.info["user"].email
    change_set = ChangeSetRow(source=source, actor=actor, note=note)
    session.add(change_set)
    session.flush()
    return change_set


def record_status(session, device, from_status, change_set, reason=None) -> None:
    session.add(DeviceStatusHistoryRow(
        device_id=device.id, from_status=from_status, to_status=device.status,
        changed_by=change_set.actor, reason=reason, change_set_id=change_set.id,
    ))


# before = (rack_id, position_u, face) prior to the change
def record_placement(session, device, before, change_set, reason=None) -> None:
    from_rack, from_u, from_face = before
    session.add(DevicePlacementHistoryRow(
        device_id=device.id,
        from_rack_id=from_rack, from_position_u=from_u, from_face=from_face if from_rack else None,
        to_rack_id=device.rack_id, to_position_u=device.position_u,
        to_face=device.face if device.rack_id else None,
        changed_by=change_set.actor, reason=reason, change_set_id=change_set.id,
    ))


def record_rename(session, device, old_name: str, change_set) -> None:
    session.add(DeviceNameHistoryRow(
        device_id=device.id, old_name=old_name, new_name=device.host_name,
        changed_by=change_set.actor, change_set_id=change_set.id,
    ))
