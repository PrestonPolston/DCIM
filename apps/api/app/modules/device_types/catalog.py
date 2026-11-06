from app.modules.device_types.schemas import DeviceProfile
from app.enums import AssetTypeLiteral
"""Flat profile catalog for the palette and reports: GET /profiles (one joined query, no N+1)."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import and_, case, or_
from sqlmodel import Session, func, select

from app.db import get_session
from app.modules.auth.deps import ADMIN, TECH, get_current_user
from app.modules.device_types.models import DeviceTypeProfileRow as P, DeviceTypeRow as T
from app.modules.devices.models import DeviceRow
from app.pagination import Pagination, contains

router = APIRouter(dependencies=[Depends(get_current_user)], tags=["device-types"])

STATUS = P.status
SORTS = {"id": P.id, "name": P.name, "manufacturer": T.manufacturer, "model": T.name, "u_height": P.u_height,
         "device_count": None}


from app.modules.images.refs import ProfileImageRef  # noqa: E402


class ProfileListItem(BaseModel):
    id: int
    name: str
    device_type_id: int
    manufacturer: str
    model: str
    u_height: int
    is_full_depth: bool
    width_mm: float | None
    height_mm: float | None
    depth_mm: float | None
    power_type: str | None
    airflow: str | None
    asset_type: AssetTypeLiteral | None  # the device type's asset type
    effective_asset_type: AssetTypeLiteral | None
    color_hex: str | None
    is_default: bool
    status: Literal["draft", "published", "retired"]
    readiness: dict
    usable: bool = False
    usable_issue: str | None = None
    usable_issues: list[str] = []
    mounting: str | None = None
    weight_kg: float | None = None
    orientation: str | None = None
    device_count: int
    front_image: ProfileImageRef | None = None
    rear_image: ProfileImageRef | None = None
    front_image_url: str | None = None  # DEPRECATED alias of front_image.url (kept until the web confirms)


@router.get("/profiles", response_model=list[ProfileListItem])
def list_profiles(
    response: Response,
    device_type_id: int | None = Query(None),
    q: str | None = Query(None, max_length=100, description="Profile name, manufacturer or model"),
    manufacturer: str | None = Query(None, max_length=255),
    asset_type: AssetTypeLiteral | None = Query(None),
    status: list[Literal["draft", "published", "retired"]] | None = Query(None),
    in_use: bool | None = Query(None, description="true = used by at least one device"),
    orientation: Literal["port_front", "power_front"] | None = Query(None),
    usable: bool | None = Query(None, description="true = only profiles usable for new devices (palette); "
                                                  "false = only unusable ones"),
    sort: str = Query("manufacturer,model,name", description=f"Comma list of {sorted(SORTS)}; '-' = descending"),
    page: Pagination = Depends(),
    session: Session = Depends(get_session),
):
    counts = (select(DeviceRow.profile_id.label("pid"), func.count().label("n"))
              .where(DeviceRow.deleted_at.is_(None), DeviceRow.profile_id.is_not(None))
              .group_by(DeviceRow.profile_id).subquery())
    n = func.coalesce(counts.c.n, 0)
    stmt = (select(P, T, n.label("device_count"), STATUS.label("status"))
            .join(T, T.id == P.device_type_id).outerjoin(counts, counts.c.pid == P.id))
    if device_type_id is not None:
        stmt = stmt.where(P.device_type_id == device_type_id)
    if q:
        stmt = stmt.where(or_(contains(P.name, q), contains(T.manufacturer, q), contains(T.name, q)))
    if manufacturer:
        stmt = stmt.where(func.lower(T.manufacturer) == manufacturer.strip().lower())
    if asset_type:
        stmt = stmt.where(T.asset_type == asset_type)
    if status:
        stmt = stmt.where(STATUS.in_(status))
    if in_use is not None:
        stmt = stmt.where(n > 0 if in_use else n == 0)
    if orientation:
        stmt = stmt.where(P.orientation == orientation)
    if usable is not None:
        # single source of truth: the Python usability() rule decides, SQL only narrows to its ids
        from app.modules.device_types.lifecycle import usable_profile_ids
        cands = session.exec(select(P).where(P.id.in_(stmt.with_only_columns(P.id, maintain_column_froms=True)))).all()
        ok = usable_profile_ids(session, list(cands))
        from sqlalchemy import true
        stmt = stmt.where(P.id.in_(ok) if usable else (P.id.not_in(ok) if ok else true()))
    order = []
    for part in [p.strip() for p in sort.split(",") if p.strip()]:
        key = part.lstrip("-")
        if key not in SORTS:
            raise HTTPException(422, f"Unknown sort field '{key}'")
        col = n if key == "device_count" else SORTS[key]
        order.append(col.desc() if part.startswith("-") else col.asc())
    total = session.exec(select(func.count()).select_from(stmt.with_only_columns(P.id, maintain_column_froms=True).subquery())).one()
    response.headers["X-Total-Count"] = str(total)
    rows = session.exec(stmt.order_by(*order, P.id).offset(page.offset).limit(page.limit)).all()
    from app.modules.images.refs import image_refs
    refs = image_refs(session, [r[0].id for r in rows])
    from app.modules.device_types.lifecycle import readiness_map, usability
    ready = readiness_map(session, [r[0] for r in rows])
    use = {p.id: usability(st, ready[p.id]) for p, _, _, st in rows}
    return [ProfileListItem(
        front_image=refs.get((p.id, "front")), rear_image=refs.get((p.id, "rear")), front_image_url=(refs.get((p.id, "front")) or {}).get("url"),
        id=p.id, name=p.name, device_type_id=t.id, manufacturer=t.manufacturer, model=t.name, u_height=p.u_height,
        is_full_depth=p.is_full_depth, width_mm=p.width_mm, height_mm=p.height_mm, depth_mm=p.depth_mm,
        power_type=p.power_type, airflow=p.airflow, asset_type=t.asset_type, effective_asset_type=t.asset_type,
        color_hex=p.color_hex, is_default=p.is_default, status=st, device_count=cnt, readiness=ready[p.id], usable=use[p.id][0], usable_issue=(use[p.id][1] or [None])[0],
        usable_issues=use[p.id][1], mounting=p.mounting, weight_kg=p.weight_kg, orientation=p.orientation,
    ) for p, t, cnt, st in rows]


@router.post("/profiles/{profile_id}/publish", dependencies=[Depends(ADMIN)], response_model=DeviceProfile)
def publish_profile_flat(profile_id: int, session: Session = Depends(get_session)):
    """Same as POST /device-types/{tid}/profiles/{pid}/publish."""
    from app.modules.device_types.profiles import publish_profile
    profile = session.get(P, profile_id)
    if profile is None:
        raise HTTPException(404, "Profile not found")
    return publish_profile(profile.device_type_id, profile_id, session)


class CloneIn(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128,
                             description="Default: '<name> v<version>', or '<name> (power front|port front)' with swap_faces")
    swap_faces: bool = Field(False, description="Swap front/rear images and flip orientation (power/port-front variant)")


class AdoptIn(BaseModel):
    device_ids: list[int] | None = Field(None, max_length=10000)
    all: bool = Field(False, description="Every device on the profile this one supersedes")


class AdoptOut(BaseModel):
    profile_id: int
    moved: int
    device_ids: list[int]


def _flat(session: Session, profile_id: int) -> P:
    profile = session.get(P, profile_id)
    if profile is None:
        raise HTTPException(404, "Profile not found")
    return profile


@router.post("/profiles/{profile_id}/clone", dependencies=[Depends(ADMIN)], response_model=DeviceProfile,
             status_code=201)
def clone_profile(profile_id: int, payload: CloneIn | None = None, session: Session = Depends(get_session)):
    """New draft version of a profile (fields + images copied, version+1, supersedes_profile_id)."""
    from app.modules.device_types.lifecycle import clone
    from app.modules.device_types.profiles import with_images
    new = clone(session, _flat(session, profile_id), payload.name if payload else None,
                swap_faces=bool(payload and payload.swap_faces))
    session.commit()
    session.refresh(new)
    return with_images(session, [new])[0]


@router.post("/profiles/{profile_id}/retire", dependencies=[Depends(ADMIN)], response_model=DeviceProfile)
def retire_profile(profile_id: int, session: Session = Depends(get_session)):
    from app.modules.device_types.lifecycle import retire
    from app.modules.device_types.profiles import with_images
    profile = retire(session, _flat(session, profile_id))
    session.commit()
    session.refresh(profile)
    return with_images(session, [profile])[0]


@router.post("/profiles/{profile_id}/adopt", dependencies=[Depends(TECH)], response_model=AdoptOut)
def adopt_profile(profile_id: int, payload: AdoptIn, session: Session = Depends(get_session)):
    """Move devices onto this published profile; fit re-checked per device; all-or-nothing (409 conflicts[])."""
    from app.modules.device_types.lifecycle import adopt
    if not payload.all and not payload.device_ids:
        raise HTTPException(422, {"code": "nothing_to_adopt", "message": "Pass device_ids or all=true"})
    devices = adopt(session, _flat(session, profile_id), payload.device_ids, payload.all)
    session.commit()
    return AdoptOut(profile_id=profile_id, moved=len(devices), device_ids=[d.id for d in devices])
