from fastapi import HTTPException
from app.settings import get_settings
from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field
from app.enums import FaceLiteral as Face
from sqlmodel import Session, func, or_, select

from app.db import commit_or_409, get_session
from app.modules.auth.deps import ADMIN, TECH, get_current_user
from app.modules.devices.csv_io import export_devices, import_devices, read_csv_body
from app.modules.devices.models import DeviceRow
from app.modules.devices.schemas import Device, DeviceCreate, RackDeviceCreate, DeviceUpdate, ImportResult, NameHistory
from app.modules.devices import lifecycle
from app.modules.devices.service import device_out, find_device
from app.modules.history.models import DeviceNameHistoryRow
from app.modules.history.service import new_change_set
from app.modules.audit.service import record_audit
from app.modules.devices.service import hard_delete_device
from app.settings import Settings, get_settings
from app.timestamps import utcnow
from app.enums import DeviceStatusLiteral as Status
from app.modules.locations.models import RackRow, RackRowRow
from app.modules.locations.service import alias_param
from app.pagination import Pagination, contains, paginate

router = APIRouter(prefix="/devices", tags=["devices"], dependencies=[Depends(get_current_user)])
SERIAL_CONFLICT = "A device with this serial_number (or host name in this cabinet) already exists"


SORT_FIELDS = ("id", "host_name", "status", "serial_number", "rack_id", "position_u", "device_type_id",
               "owner", "eos_date", "created_at", "updated_at")


# "host_name,-position_u" -> ORDER BY expressions (id always last as a tiebreak); 422 on unknown fields
def parse_sort(sort: str | None) -> list:
    order = []
    for part in [p.strip() for p in (sort or "").split(",") if p.strip()]:
        name = part.lstrip("-+")
        if name not in SORT_FIELDS:
            raise HTTPException(status_code=422, detail=f"Cannot sort by '{name}'; allowed: {', '.join(SORT_FIELDS)}")
        col = getattr(DeviceRow, name)
        order.append(col.desc() if part.startswith("-") else col.asc())
    return order


# Shared filters for list and export
class DeviceFilters:
    def __init__(
        self,
        rack_id: list[int] | None = Query(None, description="Repeatable: ?rack_id=1&rack_id=2"),
        hall_id: int | None = Query(None, description="Devices in any cabinet of this hall"),
        room_id: int | None = Query(None, description="Alias of hall_id"),
        row_id: int | None = Query(None, description="Devices in any cabinet of this row"),
        device_type_id: int | None = Query(None),
        status: list[Status] | None = Query(None, description="Repeatable: ?status=install&status=active"),
        sort: str | None = Query(None, max_length=200, description="Comma list, '-' = descending; fields: " + ", ".join(SORT_FIELDS)),
        owner: str | None = Query(None, max_length=255, description="Exact owner, case-insensitive"),
        unplaced: bool | None = Query(None, description="true = not in a rack; false = in a rack"),
        missing_serial: bool | None = Query(None, description="true = no serial_number (incl. serial_unavailable); false = has one"),
        q: str | None = Query(None, max_length=100, description="Case-insensitive host name/serial number search"),
        needs_review: bool | None = Query(None, description="true = flagged (placed_without_profile, profile_not_published)"),
    ):
        self.needs_review = needs_review
        self.rack_id, self.device_type_id, self.status, self.q = rack_id, device_type_id, status, q
        self.hall_id = alias_param("hall_id", hall_id, "room_id", room_id)
        self.row_id = row_id
        self.order = parse_sort(sort)
        self.unplaced = unplaced
        self.owner = owner
        self.missing_serial = missing_serial

    def apply(self, statement):
        statement = statement.where(DeviceRow.deleted_at.is_(None))  # hide soft-deleted
        if self.rack_id:
            statement = statement.where(DeviceRow.rack_id.in_(self.rack_id))
        if self.row_id is not None:
            statement = statement.where(DeviceRow.rack_id.in_(select(RackRow.id).where(RackRow.row_id == self.row_id)))
        if self.hall_id is not None:
            statement = statement.where(DeviceRow.rack_id.in_(
                select(RackRow.id).join(RackRowRow, RackRowRow.id == RackRow.row_id)
                .where(RackRowRow.hall_id == self.hall_id)))
        if self.device_type_id is not None:
            statement = statement.where(DeviceRow.device_type_id == self.device_type_id)
        if self.unplaced is True:
            statement = statement.where(DeviceRow.rack_id.is_(None))
        elif self.unplaced is False:
            statement = statement.where(DeviceRow.rack_id.is_not(None))
        if self.needs_review is not None:
            statement = statement.where(DeviceRow.needs_review.is_(self.needs_review))
        if self.missing_serial is True:
            statement = statement.where(DeviceRow.serial_number.is_(None))
        elif self.missing_serial is False:
            statement = statement.where(DeviceRow.serial_number.is_not(None))
        if self.owner:
            statement = statement.where(func.lower(DeviceRow.owner) == self.owner.strip().lower())
        if self.status:
            statement = statement.where(DeviceRow.status.in_(self.status))
        if self.q:
            statement = statement.where(
                or_(contains(DeviceRow.host_name, self.q), contains(DeviceRow.serial_number, self.q),
                    DeviceRow.id.in_(select(DeviceNameHistoryRow.device_id)
                                     .where(contains(DeviceNameHistoryRow.old_name, self.q))))
            )
        return statement


# List devices (paginated, filtered)
@router.get("", response_model=list[Device])
def list_devices(
    response: Response,
    filters: DeviceFilters = Depends(),
    page: Pagination = Depends(),
    session: Session = Depends(get_session),
):
    statement = filters.apply(select(DeviceRow)).order_by(*filters.order)
    return device_out(session, paginate(session, statement, page, response, DeviceRow.id))


# Export devices as CSV (same filters as the list, no pagination)
@router.get("/export", response_class=Response, responses={200: {"content": {"text/csv": {}}}})
def export_devices_csv(filters: DeviceFilters = Depends(), session: Session = Depends(get_session)):
    devices = session.exec(filters.apply(select(DeviceRow)).order_by(*filters.order, DeviceRow.id)).all()
    return Response(
        export_devices(session, devices),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="devices.csv"'},
    )


# Import devices from a CSV body (Content-Type: text/csv). dry_run=true only validates.
@router.post(
    "/import", dependencies=[Depends(TECH)], response_model=ImportResult,
    openapi_extra={"requestBody": {"required": True, "content": {"text/csv": {"schema": {"type": "string"}}}}},
)
def import_devices_csv(
    csv_text: str = Depends(read_csv_body),
    dry_run: bool = Query(True, description="Validate only; save nothing"),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    return import_devices(session, csv_text, dry_run, max_rows=settings.csv_max_rows)


# Create a device
@router.post("", dependencies=[Depends(TECH)], response_model=Device, status_code=201)
def create_device(payload: DeviceCreate, session: Session = Depends(get_session)):
    change_set = new_change_set(session, "api")
    device = lifecycle.create(session, DeviceRow(**payload.model_dump()), change_set)
    commit_or_409(session, SERIAL_CONFLICT)
    session.refresh(device)
    return device_out(session, [device])[0]


rack_devices_router = APIRouter(tags=["devices"], dependencies=[Depends(get_current_user)])


# Drag-to-rack placement: builds the same DeviceCreate as POST /devices and runs the same create path
@rack_devices_router.post("/racks/{rack_id}/devices", dependencies=[Depends(TECH)], response_model=Device,
                          status_code=201)
def place_new_device(rack_id: int, payload: RackDeviceCreate, session: Session = Depends(get_session)):
    rack = session.get(RackRow, rack_id)
    if rack is None or rack.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Cabinet not found")
    return create_device(DeviceCreate(**payload.model_dump(), rack_id=rack_id), session)


class FitCheckIn(BaseModel):
    profile_id: int
    position_u: int = Field(ge=1)
    face: Face = "front"
    device_id: int | None = Field(None, description="Ignore this device's own slot (moving it)")


class FitCheckOut(BaseModel):
    fits: bool
    conflicts: list[dict]


# Item 42: would this profile fit here? Same validation as the real placement, nothing written.
@rack_devices_router.post("/racks/{rack_id}/fit-check", response_model=FitCheckOut)
def fit_check(rack_id: int, payload: FitCheckIn, session: Session = Depends(get_session)):
    from app.modules.devices.service import validate_placement
    rack = session.get(RackRow, rack_id)
    if rack is None or rack.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Cabinet not found")
    probe = DeviceRow(id=payload.device_id, host_name="(fit-check)", rack_id=rack_id,
                      position_u=payload.position_u, face=payload.face, profile_id=payload.profile_id)
    try:
        with session.no_autoflush:
            validate_placement(session, probe, require=True)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {"code": f"http_{exc.status_code}",
                                                                  "message": str(exc.detail)}
        return FitCheckOut(fits=False, conflicts=[{"status": exc.status_code, **detail}])
    finally:
        session.expunge_all()
    return FitCheckOut(fits=True, conflicts=[])


# Get one device by id
@router.get("/{device_id}", response_model=Device)
def get_device(device_id: int, session: Session = Depends(get_session)):
    return device_out(session, [find_device(session, device_id)])[0]


# Update a device (partial; e.g. {"status": "decom"})
@router.patch("/{device_id}", dependencies=[Depends(TECH)], response_model=Device)
def update_device(
    device_id: int, payload: DeviceUpdate, session: Session = Depends(get_session)
):
    device = find_device(session, device_id)
    changes = payload.model_dump(exclude_unset=True)
    recommission = changes.pop("recommission", False)
    try:
        change_set = new_change_set(session, "api")
        lifecycle.update(session, device, changes, change_set, recommission=recommission)
    except Exception:
        session.rollback()
        raise
    commit_or_409(session, SERIAL_CONFLICT)
    session.refresh(device)
    return device_out(session, [device])[0]


# Delete a device: soft delete (decom + unrack + hide). ?hard=true is admin-only.
@router.delete("/{device_id}", dependencies=[Depends(ADMIN)], status_code=204)
def delete_device(
    device_id: int,
    hard: bool = Query(False, description="Permanently delete (admin only)"),
    session: Session = Depends(get_session),
):
    device = find_device(session, device_id)
    if hard:
        if not get_settings().hard_delete_enabled:  # DB Architect R1 still BLOCKED
            raise HTTPException(403, "Hard delete is disabled (pending approval); use soft delete")
        hard_delete_device(session, device)
        session.commit()
        return Response(status_code=204)
    change_set = new_change_set(session, "api", note=f"soft delete device {device.id}")
    lifecycle.decommission(session, device, change_set, reason="device deleted")
    record_audit(session, None, "device.delete", "device", device.id, before=lifecycle.snapshot(device))
    device.deleted_at = utcnow()
    device.deleted_by = change_set.actor
    session.commit()
    return Response(status_code=204)


# Previous host names of a device, newest first
@router.get("/{device_id}/name-history", response_model=list[NameHistory])
def device_name_history(device_id: int, session: Session = Depends(get_session)):
    find_device(session, device_id)
    return session.exec(select(DeviceNameHistoryRow).where(DeviceNameHistoryRow.device_id == device_id)
                        .order_by(DeviceNameHistoryRow.id.desc())).all()
