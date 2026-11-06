from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlmodel import Session, func, select

from app.db import get_session
from app.modules.auth.deps import ADMIN, TECH, get_current_user
from app.modules.device_types.models import DeviceTypeProfileRow, DeviceTypeRow
from app.modules.devices.lifecycle import decommission
from app.modules.devices.models import DeviceRow
from app.modules.history.service import new_change_set
from app.modules.locations.models import HallRow, RackRow, RackRowRow, SiteRow
from app.modules.locations.schemas import (
    ElevationDevice,
    Hall,
    HallCreate,
    HallLayout,
    HallUpdate,
    Rack,
    RackCreate,
    RackElevation, RowFront,
    RackLayout,
    RackUpdate,
    Row,
    RowCreate,
    RowLayout,
    RowUpdate,
    Site,
    SiteCreate,
    SiteUpdate,
)
from app.modules.locations.service import (
    alias_param, default_site, ensure_no_children, get_or_404, make_default, save,
)
from app.pagination import Pagination, contains, paginate
from app.timestamps import utcnow

FLOOR_FIELDS = {"pos_x", "pos_y", "orientation"}
router = APIRouter(dependencies=[Depends(get_current_user)])


# ---- Sites ----
@router.get("/sites", response_model=list[Site], tags=["sites"])
def list_sites(
    response: Response,
    q: str | None = Query(None, max_length=100, description="Case-insensitive name search"),
    page: Pagination = Depends(),
    session: Session = Depends(get_session),
):
    statement = select(SiteRow)
    if q:
        statement = statement.where(contains(SiteRow.name, q))
    return paginate(session, statement, page, response, SiteRow.id)


@router.post("/sites", dependencies=[Depends(ADMIN)], response_model=Site, status_code=201, tags=["sites"])
def create_site(payload: SiteCreate, session: Session = Depends(get_session)):
    site = SiteRow(**payload.model_dump(exclude={"is_default"}))
    if payload.is_default:
        session.add(site)
        session.flush()
        make_default(session, site)
    return save(session, site, "Site name already exists here")


@router.get("/sites/{site_id}", response_model=Site, tags=["sites"])
def get_site(site_id: int, session: Session = Depends(get_session)):
    return get_or_404(session, SiteRow, site_id, "Site")


@router.patch("/sites/{site_id}", dependencies=[Depends(ADMIN)], response_model=Site, tags=["sites"])
def update_site(site_id: int, payload: SiteUpdate, session: Session = Depends(get_session)):
    obj = get_or_404(session, SiteRow, site_id, "Site")
    changes = payload.model_dump(exclude_unset=True)
    flag = changes.pop("is_default", None)
    if flag is False and obj.is_default:
        raise HTTPException(status_code=409, detail="This is the default site; make another site the default instead")
    if flag:
        make_default(session, obj)
    for key, value in changes.items():
        setattr(obj, key, value)
    return save(session, obj, "Site name already exists here")


@router.delete("/sites/{site_id}", dependencies=[Depends(ADMIN)], status_code=204, tags=["sites"])
def delete_site(site_id: int, session: Session = Depends(get_session)):
    obj = get_or_404(session, SiteRow, site_id, "Site")
    if obj.is_default:
        raise HTTPException(status_code=409, detail="The default site cannot be deleted; make another site the default first")
    ensure_no_children(session, HallRow, HallRow.site_id, obj.id, "Site still has halls; remove them first")
    session.delete(obj)
    session.commit()
    return Response(status_code=204)


# ---- Halls ----
@router.get("/halls", response_model=list[Hall], tags=["halls"])
def list_halls(
    response: Response,
    site_id: int | None = Query(None, description="Filter by parent site"),
    building_id: int | None = Query(None, description="Alias of site_id"),
    q: str | None = Query(None, max_length=100, description="Case-insensitive name search"),
    page: Pagination = Depends(),
    session: Session = Depends(get_session),
):
    site_id = alias_param("site_id", site_id, "building_id", building_id)
    statement = select(HallRow)
    if site_id is not None:
        statement = statement.where(HallRow.site_id == site_id)
    if q:
        statement = statement.where(contains(HallRow.name, q))
    return paginate(session, statement, page, response, HallRow.id)


@router.post("/halls", dependencies=[Depends(ADMIN)], response_model=Hall, status_code=201, tags=["halls"])
def create_hall(payload: HallCreate, session: Session = Depends(get_session)):
    data = payload.model_dump()
    if data["site_id"] is None:
        data["site_id"] = default_site(session).id
    else:
        get_or_404(session, SiteRow, data["site_id"], "Site")
    return save(session, HallRow(**data), "Hall name already exists here")


@router.get("/halls/{hall_id}", response_model=Hall, tags=["halls"])
def get_hall(hall_id: int, session: Session = Depends(get_session)):
    return get_or_404(session, HallRow, hall_id, "Hall")


# Hall floor plan: the hall with its rows and their racks (positions + U usage)
@router.get("/halls/{hall_id}/layout", response_model=HallLayout, tags=["halls"])
def get_hall_layout(hall_id: int, session: Session = Depends(get_session)):
    hall = get_or_404(session, HallRow, hall_id, "Hall")
    rows = session.exec(
        select(RackRowRow).where(RackRowRow.hall_id == hall.id).order_by(RackRowRow.id)
    ).all()
    racks = session.exec(
        select(RackRow)
        .where(RackRow.row_id.in_([r.id for r in rows]), RackRow.deleted_at.is_(None))
        .order_by(RackRow.id)
    ).all()
    usage = {
        rack_id: (count, used or 0)
        for rack_id, count, used in session.exec(
            select(DeviceRow.rack_id, func.count(DeviceRow.id), func.sum(func.coalesce(DeviceTypeRow.u_height, 1)))
            .outerjoin(DeviceTypeRow, DeviceTypeRow.id == DeviceRow.device_type_id)
            .where(DeviceRow.rack_id.in_([r.id for r in racks]))
            .group_by(DeviceRow.rack_id)
        ).all()
    }
    racks_by_row: dict[int, list[RackLayout]] = {r.id: [] for r in rows}
    row_orientation = {r.id: r.orientation for r in rows}
    for rack in racks:
        count, used = usage.get(rack.id, (0, 0))
        racks_by_row[rack.row_id].append(
            RackLayout(**rack.model_dump(), device_count=count,
                       effective_orientation=rack.orientation or row_orientation[rack.row_id], u_used=used,
                       u_free=max(rack.u_height - used, 0))
        )
    return HallLayout(
        **hall.model_dump(),
        rows=[RowLayout(**r.model_dump(), racks=racks_by_row[r.id]) for r in rows],
    )


@router.patch("/halls/{hall_id}", dependencies=[Depends(ADMIN)], response_model=Hall, tags=["halls"])
def update_hall(hall_id: int, payload: HallUpdate, session: Session = Depends(get_session)):
    obj = get_or_404(session, HallRow, hall_id, "Hall")
    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(obj, key, value)
    return save(session, obj, "Hall name already exists here")


@router.delete("/halls/{hall_id}", dependencies=[Depends(ADMIN)], status_code=204, tags=["halls"])
def delete_hall(hall_id: int, session: Session = Depends(get_session)):
    obj = get_or_404(session, HallRow, hall_id, "Hall")
    ensure_no_children(session, RackRowRow, RackRowRow.hall_id, obj.id, "Hall still has rows; remove them first")
    session.delete(obj)
    session.commit()
    return Response(status_code=204)


# ---- Rows ----
@router.get("/rows", response_model=list[Row], tags=["rows"])
def list_rows(
    response: Response,
    hall_id: int | None = Query(None, description="Filter by parent hall"),
    room_id: int | None = Query(None, description="Alias of hall_id"),
    q: str | None = Query(None, max_length=100, description="Case-insensitive name search"),
    page: Pagination = Depends(),
    session: Session = Depends(get_session),
):
    hall_id = alias_param("hall_id", hall_id, "room_id", room_id)
    statement = select(RackRowRow)
    if hall_id is not None:
        statement = statement.where(RackRowRow.hall_id == hall_id)
    if q:
        statement = statement.where(contains(RackRowRow.name, q))
    return paginate(session, statement, page, response, RackRowRow.id)


@router.post("/rows", dependencies=[Depends(ADMIN)], response_model=Row, status_code=201, tags=["rows"])
def create_row(payload: RowCreate, session: Session = Depends(get_session)):
    get_or_404(session, HallRow, payload.hall_id, "Hall")
    return save(session, RackRowRow(**payload.model_dump()), "Row name already exists here")


@router.get("/rows/{row_id}", response_model=Row, tags=["rows"])
def get_row(row_id: int, session: Session = Depends(get_session)):
    return get_or_404(session, RackRowRow, row_id, "Row")


@router.patch("/rows/{row_id}", dependencies=[Depends(ADMIN)], response_model=Row, tags=["rows"])
def update_row(row_id: int, payload: RowUpdate, session: Session = Depends(get_session)):
    obj = get_or_404(session, RackRowRow, row_id, "Row")
    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(obj, key, value)
    return save(session, obj, "Row name already exists here")


@router.delete("/rows/{row_id}", dependencies=[Depends(ADMIN)], status_code=204, tags=["rows"])
def delete_row(row_id: int, session: Session = Depends(get_session)):
    obj = get_or_404(session, RackRowRow, row_id, "Row")
    ensure_no_children(session, RackRow, RackRow.row_id, obj.id, "Row still has cabinets; remove them first")
    purge_deleted_racks(session, obj.id)
    session.delete(obj)
    session.commit()
    return Response(status_code=204)


# ---- Racks ----
@router.get("/racks", response_model=list[Rack], tags=["racks"])
def list_racks(
    response: Response,
    row_id: int | None = Query(None, description="Filter by parent row"),
    hall_id: int | None = Query(None, description="Filter by hall (through rows)"),
    room_id: int | None = Query(None, description="Alias of hall_id"),
    q: str | None = Query(None, max_length=100, description="Case-insensitive name search"),
    page: Pagination = Depends(),
    session: Session = Depends(get_session),
):
    hall_id = alias_param("hall_id", hall_id, "room_id", room_id)
    statement = select(RackRow).where(RackRow.deleted_at.is_(None))
    if hall_id is not None:
        statement = statement.join(RackRowRow, RackRowRow.id == RackRow.row_id).where(
            RackRowRow.hall_id == hall_id
        )
    if row_id is not None:
        statement = statement.where(RackRow.row_id == row_id)
    if q:
        statement = statement.where(contains(RackRow.name, q))
    return with_effective_orientation(session, paginate(session, statement, page, response, RackRow.id))


@router.post("/racks", dependencies=[Depends(ADMIN)], response_model=Rack, status_code=201, tags=["racks"])
def create_rack(payload: RackCreate, session: Session = Depends(get_session)):
    row = get_or_404(session, RackRowRow, payload.row_id, "Row")
    rack = RackRow(**payload.model_dump())
    ensure_floor_spot_free(session, rack, row.hall_id)
    return with_effective_orientation(session, [save(session, rack, "Cabinet name already exists here")])[0]


@router.get("/racks/{rack_id}", response_model=Rack, tags=["racks"])
def get_rack(rack_id: int, session: Session = Depends(get_session)):
    return with_effective_orientation(session, [get_or_404(session, RackRow, rack_id, "Cabinet")])[0]


def elevation_devices(session: Session, rack_ids: list[int]) -> dict[int, list[ElevationDevice]]:
    """Mounted devices per rack, bottom to top, in a fixed number of queries (no N+1)."""
    from sqlalchemy import distinct, or_

    from app.modules.connections.models import ConnectionRow, DevicePortRow
    from app.modules.images.refs import image_refs
    out: dict[int, list[ElevationDevice]] = {rid: [] for rid in rack_ids}
    if not rack_ids:
        return out
    placed = session.exec(
        select(DeviceRow, DeviceTypeRow, DeviceTypeProfileRow)
        .outerjoin(DeviceTypeRow, DeviceTypeRow.id == DeviceRow.device_type_id)
        .outerjoin(DeviceTypeProfileRow, DeviceTypeProfileRow.id == DeviceRow.profile_id)
        .where(DeviceRow.rack_id.in_(rack_ids))
        .order_by(DeviceRow.rack_id, DeviceRow.position_u, DeviceRow.id)
    ).all()
    refs = image_refs(session, [d.profile_id for d, _, _ in placed])
    ids = [d.id for d, _, _ in placed]
    conn_counts = dict(session.exec(
        select(DevicePortRow.device_id, func.count(distinct(ConnectionRow.id)))
        .join(ConnectionRow, or_(ConnectionRow.port1_id == DevicePortRow.id, ConnectionRow.port2_id == DevicePortRow.id))
        .where(DevicePortRow.device_id.in_(ids)).group_by(DevicePortRow.device_id)).all()) if ids else {}
    skip = {"top_u", "device_type", "effective_front_image", "effective_rear_image", "effective_asset_type",
            "connection_count", "is_full_depth", "mounting", "depth_mm", "weight_kg", "manufacturer", "model", "orientation"}
    for device, device_type, prof in placed:
        out[device.rack_id].append(ElevationDevice(
            **device.model_dump(include=set(ElevationDevice.model_fields) - skip),
            effective_front_image=refs.get((device.profile_id, "front")),
            effective_rear_image=refs.get((device.profile_id, "rear")),
            effective_asset_type=device.asset_type or (device_type.asset_type if device_type else None),
            top_u=device.position_u + (device_type.u_height if device_type else 1) - 1,
            device_type=device_type.model_dump() if device_type else None,
            connection_count=conn_counts.get(device.id, 0),
            is_full_depth=prof.is_full_depth if prof else (device_type.is_full_depth if device_type else True),
            mounting=prof.mounting if prof else None,
            depth_mm=float(prof.depth_mm) if prof and prof.depth_mm is not None else None,
            weight_kg=float(prof.weight_kg) if prof and prof.weight_kg is not None else None,
            orientation=prof.orientation if prof else None,
            manufacturer=device_type.manufacturer if device_type else None,
            model=device_type.name if device_type else None,
        ))
    return out


def _elevation(rack: RackRow, devices: list[ElevationDevice], row_orientation: str | None) -> RackElevation:
    u_used = sum(d.top_u - d.position_u + 1 for d in devices)
    return RackElevation(
        id=rack.id, row_id=rack.row_id, name=rack.name, u_height=rack.u_height, orientation=rack.orientation,
        effective_orientation=rack.orientation or row_orientation,
        u_used=u_used, u_free=max(rack.u_height - u_used, 0), devices=devices,
    )


# Rack elevation: the rack plus its mounted devices, bottom to top
@router.get("/racks/{rack_id}/elevation", response_model=RackElevation, tags=["racks"])
def get_rack_elevation(rack_id: int, session: Session = Depends(get_session)):
    rack = get_or_404(session, RackRow, rack_id, "Cabinet")
    devices = elevation_devices(session, [rack.id])[rack.id]
    return _elevation(rack, devices, session.get(RackRowRow, rack.row_id).orientation)


# Row front view: every cabinet of the row with its elevation, in floor order (pos_x/pos_y, then name)
@router.get("/rows/{row_id}/front", response_model=RowFront, tags=["rows"])
def get_row_front(row_id: int, session: Session = Depends(get_session)):
    row = get_or_404(session, RackRowRow, row_id, "Row")
    racks = session.exec(select(RackRow).where(RackRow.row_id == row.id, RackRow.deleted_at.is_(None))
                         .order_by(RackRow.pos_x.is_(None), RackRow.pos_x, RackRow.pos_y.is_(None), RackRow.pos_y,
                                   RackRow.name, RackRow.id)).all()
    by_rack = elevation_devices(session, [r.id for r in racks])
    return RowFront(id=row.id, hall_id=row.hall_id, name=row.name, orientation=row.orientation,
                    racks=[_elevation(r, by_rack[r.id], row.orientation) for r in racks])


@router.patch("/racks/{rack_id}", dependencies=[Depends(TECH)], response_model=Rack, tags=["racks"])
def update_rack(rack_id: int, payload: RackUpdate, session: Session = Depends(get_session)):
    obj = get_or_404(session, RackRow, rack_id, "Cabinet")
    changes = payload.model_dump(exclude_unset=True)
    # technicians may only move racks on the floor plan
    if session.info["user"].role != "admin" and not set(changes) <= FLOOR_FIELDS:
        raise HTTPException(status_code=403, detail="Technicians can only change pos_x, pos_y and orientation")
    if "u_height" in changes:
        ensure_rack_fits_devices(session, obj.id, changes["u_height"])
    for key, value in changes.items():
        setattr(obj, key, value)
    with session.no_autoflush:
        try:
            ensure_floor_spot_free(session, obj, session.get(RackRowRow, obj.row_id).hall_id)
        except HTTPException:
            session.rollback()
            raise
    return with_effective_orientation(session, [save(session, obj, "Cabinet name already exists here")])[0]


@router.delete("/racks/{rack_id}", dependencies=[Depends(ADMIN)], status_code=204, tags=["racks"])
def delete_rack(rack_id: int, session: Session = Depends(get_session)):
    obj = get_or_404(session, RackRow, rack_id, "Cabinet")
    # D3: soft-delete the rack; every device in it goes to decom (unracked) in one change set
    change_set = new_change_set(session, "api", note=f"delete rack {obj.id}")
    devices = session.exec(select(DeviceRow).where(DeviceRow.rack_id == obj.id)).all()
    for device in devices:
        decommission(session, device, change_set, reason=f"cabinet '{obj.name}' deleted")
    obj.deleted_at = utcnow()
    obj.deleted_by = change_set.actor
    session.commit()
    return Response(status_code=204, headers={"X-Decommissioned-Count": str(len(devices))})


# Helper: refuse to shrink a rack below its highest mounted device
def ensure_rack_fits_devices(session: Session, rack_id: int, new_height: int):
    top = session.exec(
        select(func.max(DeviceRow.position_u + func.coalesce(DeviceTypeRow.u_height, 1) - 1))
        .outerjoin(DeviceTypeRow, DeviceTypeRow.id == DeviceRow.device_type_id)
        .where(DeviceRow.rack_id == rack_id)
    ).one()
    if top is not None and top > new_height:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot shrink cabinet to {new_height}U: a device occupies up to U{top}",
        )


# Helper: two racks in the same hall can't share a floor grid cell
def ensure_floor_spot_free(session: Session, rack: RackRow, hall_id: int):
    if rack.pos_x is None or rack.pos_y is None:
        return
    statement = (
        select(RackRow)
        .join(RackRowRow, RackRowRow.id == RackRow.row_id)
        .where(RackRowRow.hall_id == hall_id, RackRow.pos_x == rack.pos_x, RackRow.pos_y == rack.pos_y)
        .where(RackRow.deleted_at.is_(None))
    )
    if rack.id is not None:
        statement = statement.where(RackRow.id != rack.id)
    other = session.exec(statement).first()
    if other:
        raise HTTPException(
            status_code=409,
            detail=f"Floor position ({rack.pos_x}, {rack.pos_y}) in this hall is taken by cabinet '{other.name}'",
        )


# Helper: before deleting a row, physically remove its soft-deleted racks.
# Racks still referenced by device history must stay, so the row can't go (409).
def purge_deleted_racks(session: Session, row_id: int):
    from app.modules.history.models import DevicePlacementHistoryRow as H

    for rack in session.exec(select(RackRow).where(RackRow.row_id == row_id)).all():
        referenced = session.exec(
            select(func.count()).select_from(H).where((H.from_rack_id == rack.id) | (H.to_rack_id == rack.id))
        ).one()
        if referenced:
            raise HTTPException(
                status_code=409,
                detail="Row has deleted cabinets that are kept for device history; it cannot be deleted",
            )
        session.delete(rack)
    session.flush()


# Helper: Rack responses with effective_orientation (own value, else the row's)
def with_effective_orientation(session: Session, racks) -> list[Rack]:
    row_ids = {r.row_id for r in racks}
    rows = session.exec(select(RackRowRow).where(RackRowRow.id.in_(row_ids))).all() if row_ids else []
    by_row = {r.id: r.orientation for r in rows}
    return [
        Rack(**r.model_dump(), effective_orientation=r.orientation or by_row.get(r.row_id)) for r in racks
    ]
