from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlmodel import Session, func, or_, select, update

from app.db import get_session
from app.modules.auth.deps import ADMIN, TECH, get_current_user
from app.modules.device_types.models import DeviceTypeProfileRow, DeviceTypeRow
from app.modules.device_types.profiles import create_default_profile
from app.modules.device_types.schemas import DeviceType, DeviceTypeCreate, DeviceTypeUpdate
from app.modules.devices.models import DeviceRow
from app.modules.locations.service import ensure_no_children, get_or_404, save
from app.pagination import Pagination, contains, paginate

router = APIRouter(prefix="/device-types", tags=["device-types"], dependencies=[Depends(get_current_user)])
CONFLICT = "Device type with this manufacturer and name already exists"


# List device types (paginated, filter by manufacturer, search name/manufacturer)
@router.get("", response_model=list[DeviceType])
def list_device_types(
    response: Response,
    manufacturer: str | None = Query(None, description="Exact manufacturer"),
    q: str | None = Query(None, max_length=100, description="Case-insensitive name/manufacturer search"),
    page: Pagination = Depends(),
    session: Session = Depends(get_session),
):
    statement = select(DeviceTypeRow)
    if manufacturer:
        statement = statement.where(DeviceTypeRow.manufacturer == manufacturer)
    if q:
        statement = statement.where(
            or_(contains(DeviceTypeRow.name, q), contains(DeviceTypeRow.manufacturer, q))
        )
    return paginate(session, statement, page, response, DeviceTypeRow.id)


@router.post("", dependencies=[Depends(TECH)], response_model=DeviceType, status_code=201)
def create_device_type(payload: DeviceTypeCreate, session: Session = Depends(get_session)):
    device_type = save(session, DeviceTypeRow(**payload.model_dump()), CONFLICT)
    create_default_profile(session, device_type)
    session.commit()
    session.refresh(device_type)
    return device_type


@router.get("/{device_type_id}", response_model=DeviceType)
def get_device_type(device_type_id: int, session: Session = Depends(get_session)):
    return get_or_404(session, DeviceTypeRow, device_type_id, "Device type")


# Size/depth changes are refused while devices use the type (would silently move gear)
# Technicians may set asset_type (so older models can be completed and published); everything else is admin
@router.patch("/{device_type_id}", dependencies=[Depends(TECH)], response_model=DeviceType)
def update_device_type(
    device_type_id: int, payload: DeviceTypeUpdate, session: Session = Depends(get_session)
):
    obj = get_or_404(session, DeviceTypeRow, device_type_id, "Device type")
    changes = payload.model_dump(exclude_unset=True)
    if getattr(session.info.get("user"), "role", None) != "admin" and set(changes) - {"asset_type"}:
        raise HTTPException(403, {"code": "device_type_change_requires_admin",
                                  "message": "Technicians may only set asset_type on a model"})
    geometry_changed = any(
        k in changes and changes[k] != getattr(obj, k) for k in ("u_height", "is_full_depth")
    )
    if geometry_changed:
        in_use = session.exec(
            select(func.count()).select_from(DeviceRow).where(DeviceRow.device_type_id == obj.id)
        ).one()
        if in_use:
            raise HTTPException(
                status_code=409,
                detail="Cannot change u_height/is_full_depth while devices use this type",
            )
    non_draft = session.exec(select(DeviceTypeProfileRow.id).where(
        DeviceTypeProfileRow.device_type_id == obj.id, DeviceTypeProfileRow.status != "draft")).first()
    if non_draft is not None and (geometry_changed or ("asset_type" in changes and changes["asset_type"] is None)):
        raise HTTPException(409, {"code": "profile_published", "message":
                                  "This type has published profiles: its U height/depth are fixed and "
                                  "asset_type can't be cleared"})
    for key, value in changes.items():
        setattr(obj, key, value)
    if "u_height" in changes:  # profiles always mirror the type's U height
        session.exec(
            update(DeviceTypeProfileRow)
            .where(DeviceTypeProfileRow.device_type_id == obj.id)
            .values(u_height=changes["u_height"])
        )
    return save(session, obj, CONFLICT)


@router.delete("/{device_type_id}", dependencies=[Depends(ADMIN)], status_code=204)
def delete_device_type(device_type_id: int, session: Session = Depends(get_session)):
    obj = get_or_404(session, DeviceTypeRow, device_type_id, "Device type")
    ensure_no_children(
        session, DeviceRow, DeviceRow.device_type_id, obj.id,
        "Device type is used by devices; remove them first",
    )
    session.delete(obj)
    session.commit()
    return Response(status_code=204)
