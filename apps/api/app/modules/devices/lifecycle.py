from fastapi import HTTPException
from sqlmodel import Session

from app.db import flush_or_409

from app.modules.audit.service import record_audit
from app.modules.devices.models import DeviceRow
from app.modules.devices.service import validate_placement
from app.modules.history.models import ChangeSetRow
from app.modules.history.service import record_placement, record_rename, record_status
from app.timestamps import utcnow

CONFLICT = "A device with this serial_number (or host name in this cabinet) already exists"

# Allowed status transitions; leaving decom needs recommission=true
TRANSITIONS = {
    "install": {"active", "decom"},
    "active": {"decom"},
    "decom": set(),
}
PLACEMENT_FIELDS = ("rack_id", "position_u", "face")
STATUS_TIMESTAMP = {"install": "installed_at", "active": "activated_at", "decom": "decommissioned_at"}


def _placement(device: DeviceRow) -> tuple:
    return (device.rack_id, device.position_u, device.face)


AUDIT_FIELDS = ("host_name", "status", "serial_number", "device_type_id", "profile_id",
                "rack_id", "position_u", "face", "rack", "description", "notes", "asset_type", "eos_date",
                "app_service", "system_type", "system_type_confidence", "color_hex", "power_assignment",
                "historic_name", "owner", "project_id", "serial_unavailable", "serial_note")


def snapshot(device: DeviceRow) -> dict:
    return {k: getattr(device, k) for k in AUDIT_FIELDS}


def _audit(session: Session, action: str, device: DeviceRow, before: dict | None, after: dict | None) -> None:
    if before and after:
        keys = [k for k in after if before.get(k) != after.get(k)]
        before, after = {k: before[k] for k in keys}, {k: after[k] for k in keys}
    record_audit(session, None, action, "device", device.id, before=before, after=after,
                 import_batch_id=session.info.get("import_batch_id"))


def _stamp_status(device: DeviceRow) -> None:
    now = utcnow()
    device.status_changed_at = now
    setattr(device, STATUS_TIMESTAMP[device.status], now)


# Decommission: status=decom and free the rack position (D2)
def decommission(session: Session, device: DeviceRow, change_set: ChangeSetRow, reason: str | None = None) -> None:
    before_status, before_place, before = device.status, _placement(device), snapshot(device)
    device.status = "decom"
    device.rack_id = device.position_u = None
    device.face = "front"
    _stamp_status(device)
    if before_status != "decom":
        record_status(session, device, before_status, change_set, reason)
    if before_place[0] is not None:
        record_placement(session, device, before_place, change_set, reason or "decom auto-unrack")
    if before_status != "decom":
        _audit(session, "device.decom", device, before, snapshot(device))


# New device: validate, insert, and write its first history rows
def _check_serial(device: DeviceRow) -> None:
    if device.serial_unavailable and device.serial_number:
        raise HTTPException(status_code=422, detail={
            "code": "serial_conflict",
            "message": "serial_unavailable=true requires an empty serial_number"})


def create(session: Session, device: DeviceRow, change_set: ChangeSetRow, defer: bool = False) -> DeviceRow:
    """Validate and insert. defer=True (bulk CSV, unplaced rows only): skip the flush; the caller flushes a
    chunk and then calls after_create() for each device, so the inserts are batched."""
    _check_serial(device)
    if device.status == "decom" and device.rack_id is not None:
        raise HTTPException(status_code=422, detail="A decom device cannot be placed in a cabinet")
    validate_placement(session, device, require=True)  # D36: every new device has a published profile
    _stamp_status(device)
    if device.created_by is None and session.info.get("user") is not None:
        device.created_by = session.info["user"].email
    session.add(device)
    if defer:
        return device
    flush_or_409(session, CONFLICT)
    after_create(session, device, change_set)
    return device


def after_create(session: Session, device: DeviceRow, change_set: ChangeSetRow) -> None:
    record_status(session, device, None, change_set)
    if device.rack_id is not None:
        record_placement(session, device, (None, None, None), change_set)
    action = "device.import" if session.info.get("import_batch_id") else (
        "device.install" if device.rack_id is not None else "device.create")
    _audit(session, action, device, None, snapshot(device))


# Apply a PATCH: lifecycle rules, decom auto-unrack, placement validation, history
def update(session: Session, device: DeviceRow, changes: dict, change_set: ChangeSetRow,
           recommission: bool = False) -> DeviceRow:
    new_status = changes.pop("status", device.status)
    before_status, before_place, before = device.status, _placement(device), snapshot(device)
    old_name = device.host_name
    before_profile = device.profile_id

    if new_status != before_status:
        allowed = TRANSITIONS[before_status] | ({"install", "active"} if recommission else set())
        if new_status not in allowed:
            raise HTTPException(
                status_code=422,
                detail=f"Status cannot change from '{before_status}' to '{new_status}'"
                + (" (send recommission=true to bring a decom device back)" if before_status == "decom" else ""),
            )
    if new_status == "decom" and any(changes.get(f) is not None for f in ("rack_id", "position_u")):
        raise HTTPException(status_code=422, detail="Cannot set a cabinet placement while decommissioning")

    if device.needs_review:
        _check_flagged_edit(device, changes, new_status)
    if "device_type_id" in changes and "profile_id" not in changes \
            and changes["device_type_id"] != device.device_type_id:
        changes["profile_id"] = None  # new type: fall back to its default profile
    with session.no_autoflush:
        for key, value in changes.items():
            setattr(device, key, value)
        _check_serial(device)
        if new_status == "decom":
            validate_placement(session, _unracked_view(device), device.profile_id != before_profile)
            decommission(session, device, change_set)
            _clear_flag_if_resolved(device, session)
            if device.host_name != old_name:
                record_rename(session, device, old_name, change_set)
            return device
        if before_status == "decom" and device.rack_id is not None and new_status == "decom":
            raise HTTPException(status_code=422, detail="A decom device cannot be placed in a cabinet")
        device.status = new_status
        validate_placement(session, device, device.profile_id != before_profile)
        _clear_flag_if_resolved(device, session)
    if device.host_name != old_name:
        record_rename(session, device, old_name, change_set)
    if new_status != before_status:
        _stamp_status(device)
        record_status(session, device, before_status, change_set)
    moved = _placement(device) != before_place and (device.rack_id or before_place[0])
    if moved:
        record_placement(session, device, before_place, change_set)
    if moved:
        action = "device.unrack" if device.rack_id is None else "device.move"
    elif new_status != before_status:
        action = "device.status_change"
    else:
        action = "device.update"
    after = snapshot(device)
    if after != before:
        _audit(session, action, device, before, after)
    return device


FLAGGED_MESSAGES = {
    "placed_without_profile": "This device is in a cabinet without a profile. Only unplace, decommission, "
                              "assigning a published profile, or removal are allowed",
    "profile_not_published": "This device uses a profile that is not published. Only unplace, decommission, "
                             "switching to a published profile of the same type, or removal are allowed",
}


def _check_flagged_edit(device: DeviceRow, changes: dict, new_status: str) -> None:
    """Item 39: a needs_review device accepts only unplace, decom, or a published profile (same type)."""
    allowed = {"rack_id", "position_u", "face", "profile_id"}
    unplace = "rack_id" in changes and changes["rack_id"] is None
    ok = set(changes) <= allowed and (
        new_status == "decom" or unplace
        or ("profile_id" in changes and changes["profile_id"] is not None and not ({"rack_id", "position_u", "face"} & set(changes))))
    if new_status != device.status and new_status != "decom":
        ok = False
    if not ok:
        reason = device.needs_review_reason or "other"
        raise HTTPException(status_code=409, detail={"code": reason, "message": FLAGGED_MESSAGES.get(
            reason, "This device is flagged for review; only unplace, decommission or a profile change are allowed")})


def _clear_flag_if_resolved(device: DeviceRow, session: Session) -> None:
    if not device.needs_review:
        return
    # validate_placement passed; clear once the cause is gone (decom, a published profile, or unplaced
    # when the only problem was being placed without a profile)
    from app.modules.device_types.lifecycle import is_published
    from app.modules.device_types.models import DeviceTypeProfileRow
    profile = session.get(DeviceTypeProfileRow, device.profile_id) if device.profile_id else None
    if (device.status == "decom" or is_published(profile)
            or (device.needs_review_reason == "placed_without_profile" and device.rack_id is None)):
        device.needs_review, device.needs_review_reason = False, None


def _unracked_view(device: DeviceRow) -> DeviceRow:
    # validate non-placement fields (type/profile refs) as if unracked
    return DeviceRow(**{**device.model_dump(), "rack_id": None, "position_u": None})
