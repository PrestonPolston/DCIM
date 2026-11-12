from fastapi import HTTPException
from sqlmodel import Session, func, select

from app.modules.device_types.models import DeviceTypeProfileRow, DeviceTypeRow
from app.modules.devices.models import DeviceRow
from app.modules.locations.models import RackRow


# Helper: find a device by id or raise a 404
def find_device(session: Session, device_id: int) -> DeviceRow:
    device = session.get(DeviceRow, device_id)
    if device is None or device.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Device not found")
    return device


# Defensive only: OTHER devices already in a cabinet without a profile (pre-policy data, to be handled by
# the admin removal script) are treated as 1U blocking both faces so nothing new can overlap them.
# A device being placed always needs a complete profile (profile_required_for_placement).
_LEGACY_OCCUPANT = DeviceTypeRow(id=None, manufacturer="", name="(no profile)", u_height=1, is_full_depth=True)


def _span(position_u: int, u_height: int) -> str:
    top = position_u + u_height - 1
    return f"U{position_u}" if top == position_u else f"U{position_u}-U{top}"


# Validate a device's placement: references exist, fits in rack, no overlaps.
# Overlap rule: same U range conflicts on the same face, or on either face if
# either device is full-depth.
PROFILE_REQUIRED = "profile_required"
PROFILE_NOT_PUBLISHED = "profile_not_published"


def _profile_error(message: str, missing: list[str] | None = None, code: str = PROFILE_REQUIRED) -> HTTPException:
    detail = {"code": code, "message": message}
    if missing:
        detail["missing"] = missing
    return HTTPException(status_code=422, detail=detail)


def resolve_profile(session: Session, device: DeviceRow, profile_changed: bool = True,
                    require: bool = False) -> DeviceTypeProfileRow | None:
    """D36/p1_17: a new device (require=True) or a placed one needs a published profile.
    profile_id given: it must be published (when changed or placed); device_type_id is filled from it.
    Only device_type_id given: the type's default profile is used if it is published."""
    from app.modules.device_types.lifecycle import is_published
    needed = require or device.rack_id is not None
    if device.profile_id is None and device.device_type_id is not None:
        default = session.exec(select(DeviceTypeProfileRow).where(
            DeviceTypeProfileRow.device_type_id == device.device_type_id,
            DeviceTypeProfileRow.is_default.is_(True))).first()
        if is_published(default):
            device.profile_id = default.id
        elif needed:
            published = session.exec(select(DeviceTypeProfileRow.id).where(
                DeviceTypeProfileRow.device_type_id == device.device_type_id,
                DeviceTypeProfileRow.status == "published").order_by(DeviceTypeProfileRow.id)).first()
            err = _profile_error(
                "A device needs a published profile; this device type's default profile is not published"
                + (" (pass profile_id of a published one)" if published else ""), None,
                code=PROFILE_NOT_PUBLISHED if default else PROFILE_REQUIRED)
            if published:
                err.detail["published_profile_id"] = published
            if default is not None:
                err.detail.update(profile_id=default.id, profile_status=default.status)
            raise err
    if device.profile_id is None:
        if needed:
            raise _profile_error("A device needs a published profile (profile_id, or a device_type_id whose "
                                 "default profile is published)")
        return None
    profile = session.get(DeviceTypeProfileRow, device.profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    if device.device_type_id is None:
        device.device_type_id = profile.device_type_id
    if not is_published(profile) and (needed or profile_changed):  # unplace/decom may keep it
        err = _profile_error(f"This profile is {profile.status}; only published profiles can be used by a device",
                             None, code=PROFILE_NOT_PUBLISHED)
        err.detail.update(profile_id=profile.id, profile_status=profile.status)
        raise err
    if is_published(profile) and (profile_changed or require):  # existing devices that keep it are unaffected
        from app.modules.device_types.lifecycle import require_usable
        require_usable(session, profile)
    return profile


def validate_placement(session: Session, device: DeviceRow, profile_changed: bool = True,
                       require: bool = False) -> None:
    profile = resolve_profile(session, device, profile_changed, require)
    device_type = None
    if device.device_type_id is not None:
        device_type = session.get(DeviceTypeRow, device.device_type_id)
        if device_type is None:
            raise HTTPException(status_code=404, detail="Device type not found")

    if device.project_id is not None:
        from app.modules.directory.models import ProjectRow
        project = session.get(ProjectRow, device.project_id)
        if project is None or project.deleted_at is not None:
            raise HTTPException(status_code=404, detail="Project not found")

    if device.profile_id is not None:
        profile = session.get(DeviceTypeProfileRow, device.profile_id)
        if profile is None:
            raise HTTPException(status_code=404, detail="Profile not found")
        if profile.device_type_id != device.device_type_id:
            raise HTTPException(
                status_code=422,
                detail={"code": "profile_type_mismatch",
                        "message": "profile_id belongs to a different device type"},
            )

    if device.rack_id is None:
        if device.position_u is not None:
            raise HTTPException(status_code=422, detail="position_u requires rack_id")
        return

    rack = session.get(RackRow, device.rack_id)
    if rack is None or rack.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Cabinet not found")
    if device.position_u is None:
        raise HTTPException(status_code=422, detail="Placing a device in a cabinet requires position_u")
    # fit/overlap use the profile's dimensions
    device_type = DeviceTypeRow(id=device.device_type_id, manufacturer="", name="", u_height=profile.u_height,
                                is_full_depth=profile.is_full_depth)

    top = device.position_u + device_type.u_height - 1
    if top > rack.u_height:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Device does not fit: {_span(device.position_u, device_type.u_height)} "
                f"exceeds cabinet '{rack.name}' height of {rack.u_height}U"
            ),
        )

    same_name = session.exec(
        select(DeviceRow.id).where(
            DeviceRow.rack_id == rack.id,
            func.lower(DeviceRow.host_name) == device.host_name.lower(),
            DeviceRow.id != device.id if device.id is not None else True,
        )
    ).first()
    if same_name:
        raise HTTPException(
            status_code=409,
            detail={"code": "hostname_conflict",
                    "message": f"Host name '{device.host_name}' already exists in cabinet '{rack.name}'"},
        )

    others = session.exec(
        select(DeviceRow, DeviceTypeProfileRow)
        .outerjoin(DeviceTypeProfileRow, DeviceTypeProfileRow.id == DeviceRow.profile_id)
        .where(DeviceRow.rack_id == rack.id)
        .where(DeviceRow.id != device.id if device.id is not None else True)
    ).all()
    for other, other_type in others:
        other_type = other_type or _LEGACY_OCCUPANT
        other_top = other.position_u + other_type.u_height - 1
        ranges_overlap = device.position_u <= other_top and other.position_u <= top
        faces_clash = (
            device.face == other.face or device_type.is_full_depth or other_type.is_full_depth
        )
        if ranges_overlap and faces_clash:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Placement {_span(device.position_u, device_type.u_height)} ({device.face}) "
                    f"in cabinet '{rack.name}' overlaps device '{other.host_name}' (id {other.id}) "
                    f"at {_span(other.position_u, other_type.u_height)} ({other.face})"
                ),
            )


# Admin hard delete: full snapshot (row + history) goes to the audit log, then rows are removed
def hard_delete_device(session: Session, device: DeviceRow) -> None:
    from app.modules.audit.service import record_audit
    from app.modules.history.models import DeviceNameHistoryRow, DevicePlacementHistoryRow, DeviceStatusHistoryRow

    history = {}
    for name, model in [("status_history", DeviceStatusHistoryRow), ("placement_history", DevicePlacementHistoryRow),
                        ("name_history", DeviceNameHistoryRow)]:
        rows = session.exec(select(model).where(model.device_id == device.id)).all()
        history[name] = [r.model_dump() for r in rows]
        for r in rows:
            session.delete(r)
    from sqlalchemy import or_ as _or
    from app.modules.connections.models import ConnectionHopRow, ConnectionRow, DevicePortRow
    port_ids = list(session.exec(select(DevicePortRow.id).where(DevicePortRow.device_id == device.id)).all())
    if port_ids and session.exec(select(ConnectionRow.id).where(_or(
            ConnectionRow.port1_id.in_(port_ids), ConnectionRow.port2_id.in_(port_ids)))).first() is not None:
        raise HTTPException(status_code=409, detail={
            "code": "device_has_connections", "message": "Delete this device's connections first"})
    if port_ids and session.exec(select(ConnectionHopRow.id).where(
            ConnectionHopRow.port_id.in_(port_ids))).first() is not None:  # a panel other connections pass through
        raise HTTPException(status_code=409, detail={
            "code": "device_has_connections", "message": "Connections pass through this device's ports; delete "
                                                         "those connections first"})
    for pid in port_ids:
        session.delete(session.get(DevicePortRow, pid))
    record_audit(session, None, "device.hard_delete", "device", device.id,
                 before={"device": device.model_dump(), **history}, via="api", retention_class="restorable")
    session.flush()
    session.delete(device)


# Device responses with effective (inherited) values: device -> profile -> device type
def device_out(session: Session, devices: list[DeviceRow]) -> list:
    from app.modules.devices.schemas import Device

    type_ids = {d.device_type_id for d in devices if d.device_type_id}
    types = {t.id: t for t in session.exec(select(DeviceTypeRow).where(DeviceTypeRow.id.in_(type_ids))).all()} if type_ids else {}
    profiles = {}
    if type_ids:
        for p in session.exec(select(DeviceTypeProfileRow).where(DeviceTypeProfileRow.device_type_id.in_(type_ids))).all():
            profiles[p.id] = p
    default_profile = {p.device_type_id: p for p in profiles.values() if p.is_default}
    from app.modules.images.refs import image_refs
    imgs = image_refs(session, profiles.keys())
    out = []
    for d in devices:
        t = types.get(d.device_type_id)
        prof = profiles.get(d.profile_id) or default_profile.get(d.device_type_id)
        out.append(Device(
            **d.model_dump(),
            effective_asset_type=d.asset_type or (t.asset_type if t else None),
            effective_eos_date=d.eos_date or (t.eos_date if t else None),
            effective_color_hex=d.color_hex or getattr(prof, "color_hex", None),
            effective_front_image=imgs.get((prof.id, "front")) if prof else None,
            effective_rear_image=imgs.get((prof.id, "rear")) if prof else None,
            orientation=getattr(prof, "orientation", None),
        ))
    return out
