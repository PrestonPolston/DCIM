from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlmodel import Session, select, update

from app.db import get_session
from app.modules.auth.deps import ADMIN, TECH, get_current_user
from app.modules.device_types.models import DeviceTypeProfileRow, DeviceTypeRow
from app.modules.device_types.schemas import (DeviceProfile, DeviceProfileCreate, DeviceProfileCreateRequest,
                                              DeviceProfileUpdate)
from app.modules.locations.service import get_or_404, save

router = APIRouter(
    prefix="/device-types/{device_type_id}/profiles", tags=["device-types"],
    dependencies=[Depends(get_current_user)],
)
CONFLICT = "A profile with this name already exists for this device type"


# Helper: create the default profile for a new device type
def create_default_profile(session: Session, device_type: DeviceTypeRow) -> None:
    session.add(DeviceTypeProfileRow(
        device_type_id=device_type.id, name="default", is_default=True,
        u_height=device_type.u_height, is_full_depth=device_type.is_full_depth,
    ))


def _clear_default(session: Session, device_type_id: int) -> None:
    session.exec(
        update(DeviceTypeProfileRow)
        .where(DeviceTypeProfileRow.device_type_id == device_type_id)
        .values(is_default=False)
    )


def _get_profile(session: Session, device_type_id: int, profile_id: int) -> DeviceTypeProfileRow:
    profile = get_or_404(session, DeviceTypeProfileRow, profile_id, "Profile")
    if profile.device_type_id != device_type_id:
        get_or_404(session, DeviceTypeProfileRow, -1, "Profile")
    return profile


def with_images(session: Session, profiles: list) -> list[DeviceProfile]:
    from app.modules.images.refs import image_refs
    from app.modules.device_types.lifecycle import readiness_map, usability
    refs = image_refs(session, [p.id for p in profiles])
    ready = readiness_map(session, profiles)
    out = []
    for p in profiles:
        usable, issues = usability(p.status, ready[p.id])
        out.append(DeviceProfile.model_validate({
            **p.model_dump(), "front_image": refs.get((p.id, "front")), "rear_image": refs.get((p.id, "rear")),
            "readiness": ready.get(p.id), "usable": usable, "usable_issue": issues[0] if issues else None,
            "usable_issues": issues}))
    return out


@router.get("", response_model=list[DeviceProfile])
def list_profiles(device_type_id: int, session: Session = Depends(get_session),
                  usable: bool | None = Query(None, description="true = only usable profiles; false = only unusable")):
    get_or_404(session, DeviceTypeRow, device_type_id, "Device type")
    out = with_images(session, session.exec(
        select(DeviceTypeProfileRow)
        .where(DeviceTypeProfileRow.device_type_id == device_type_id)
        .order_by(DeviceTypeProfileRow.id)
    ).all())
    return out if usable is None else [p for p in out if p.usable == usable]  # same usability() rule as /profiles


@router.post("", dependencies=[Depends(TECH)], response_model=DeviceProfile, status_code=201)
def create_profile(device_type_id: int, payload: DeviceProfileCreateRequest, session: Session = Depends(get_session)):
    device_type = get_or_404(session, DeviceTypeRow, device_type_id, "Device type")
    asset_type = payload.asset_type
    payload = DeviceProfileCreate(**payload.model_dump(exclude={"asset_type"}))
    if asset_type is not None:
        if device_type.asset_type is None:
            device_type.asset_type = asset_type
            session.add(device_type)
        elif device_type.asset_type != asset_type:
            raise HTTPException(409, {"code": "asset_type_mismatch", "message":
                                      f"This model's asset type is {device_type.asset_type}; change it on the model"})
    if payload.is_default:
        _clear_default(session, device_type_id)
    profile = DeviceTypeProfileRow(
        **payload.model_dump(), device_type_id=device_type_id, u_height=device_type.u_height
    )
    return with_images(session, [save(session, profile, CONFLICT)])[0]


@router.get("/{profile_id}", response_model=DeviceProfile)
def get_profile(device_type_id: int, profile_id: int, session: Session = Depends(get_session)):
    return with_images(session, [_get_profile(session, device_type_id, profile_id)])[0]


@router.patch("/{profile_id}", dependencies=[Depends(ADMIN)], response_model=DeviceProfile)
def update_profile(
    device_type_id: int, profile_id: int, payload: DeviceProfileUpdate,
    session: Session = Depends(get_session),
):
    profile = _get_profile(session, device_type_id, profile_id)
    changes = payload.model_dump(exclude_unset=True)
    from app.modules.device_types.lifecycle import TEMPLATE_FIELDS
    frozen = sorted(k for k in changes if k in TEMPLATE_FIELDS and changes[k] != getattr(profile, k))
    if ("orientation" in changes and changes["orientation"] != profile.orientation and profile.status != "draft"
            and profile.orientation is not None):
        # D58: images must match the orientation; a published profile keeps it once set (setting a missing one
        # is allowed); to flip it, clone with swap_faces
        from app.modules.device_types.lifecycle import device_count
        if device_count(session, profile.id):
            raise HTTPException(409, {"code": "profile_published", "fields": ["orientation"], "message":
                                      "This profile is in use; clone it with swap_faces to change orientation"})
    if profile.status != "draft" and frozen:
        raise HTTPException(409, {"code": "profile_published", "fields": frozen, "message":
                                  f"This profile is {profile.status}; clone it into a new version to change "
                                  + ", ".join(frozen)})
    fit = sorted(k for k in changes if k in {"is_full_depth", "width_mm", "height_mm", "depth_mm", "mounting"}
                 and changes[k] != getattr(profile, k)
                 and getattr(profile, k) is not None)  # filling in a missing value (completing a draft) is fine
    if fit:
        from app.modules.device_types.lifecycle import device_count
        n = device_count(session, profile.id)
        if n:
            raise HTTPException(409, {"code": "profile_in_use", "device_count": n, "fields": fit, "message":
                                      f"{n} device(s) use this profile; clone it and adopt the devices instead"})
    if changes.get("is_default"):
        _clear_default(session, device_type_id)
    for key, value in changes.items():
        setattr(profile, key, value)
    return with_images(session, [save(session, profile, CONFLICT)])[0]


@router.post("/{profile_id}/publish", dependencies=[Depends(ADMIN)], response_model=DeviceProfile)
def publish_profile(device_type_id: int, profile_id: int, session: Session = Depends(get_session)):
    """Draft -> published once readiness.ready (422 profile_not_ready with missing[]). Idempotent."""
    from app.modules.device_types.lifecycle import publish
    profile = publish(session, _get_profile(session, device_type_id, profile_id))
    session.commit()
    session.refresh(profile)
    return with_images(session, [profile])[0]


# Devices using a deleted profile fall back to the type's default (FK SET NULL)
@router.delete("/{profile_id}", dependencies=[Depends(ADMIN)], status_code=204)
def delete_profile(device_type_id: int, profile_id: int, session: Session = Depends(get_session)):
    profile = _get_profile(session, device_type_id, profile_id)
    from app.modules.devices.models import DeviceRow
    if session.exec(select(DeviceRow.id).where(DeviceRow.profile_id == profile.id)).first() is not None:
        # p1_18: every device (incl. soft-deleted) keeps a profile; move them (adopt) or retire this one
        raise HTTPException(status_code=409, detail={
            "code": "profile_in_use", "message": "Devices use this profile; adopt them onto another or retire it"})
    if session.exec(select(DeviceTypeProfileRow.id).where(
            DeviceTypeProfileRow.supersedes_profile_id == profile.id)).first() is not None:
        raise HTTPException(status_code=409, detail={
            "code": "profile_superseded", "message": "A newer version references this profile; retire it instead"})
    session.delete(profile)
    session.commit()
    return Response(status_code=204)
