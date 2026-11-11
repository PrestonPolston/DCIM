"""Build the GET /home/search payload. Case-insensitive substring; LIKE wildcards escaped."""
from datetime import datetime

from sqlalchemy import func, or_
from sqlmodel import Session, select

from app.modules.devices.models import DeviceRow
from app.modules.history.models import DeviceNameHistoryRow
from app.modules.home.constants import SEARCH_DEFAULT_LIMIT
from app.modules.home.schemas import (
    CabinetSearchGroup,
    DeviceSearchGroup,
    HallSearchGroup,
    HomeSearch,
    ParkedTile,
    RowSearchGroup,
    SearchCabinetItem,
    SearchDeviceItem,
    SearchPlaceItem,
    SearchRowItem,
)
from app.modules.locations.models import HallRow, RackRow, RackRowRow, SiteRow
from app.pagination import contains
from app.timestamps import iso_z

DCREQS_SEARCH_PARKED = ParkedTile(
    key="dcreqs",
    message="DCREQ search is not available yet.",
)


def _count(session: Session, stmt) -> int:
    return session.exec(select(func.count()).select_from(stmt.subquery())).one()


def _device_match(q: str):
    return or_(
        contains(DeviceRow.host_name, q),
        contains(DeviceRow.serial_number, q),
        DeviceRow.id.in_(
            select(DeviceNameHistoryRow.device_id).where(contains(DeviceNameHistoryRow.old_name, q))
        ),
    )


def _devices(session: Session, q: str, limit: int) -> DeviceSearchGroup:
    base = select(DeviceRow.id).where(DeviceRow.deleted_at.is_(None), _device_match(q))
    count = _count(session, base)
    rows = session.exec(
        select(DeviceRow, RackRow.name)
        .outerjoin(RackRow, RackRow.id == DeviceRow.rack_id)
        .where(DeviceRow.deleted_at.is_(None), _device_match(q))
        .order_by(func.lower(DeviceRow.host_name), DeviceRow.id)
        .limit(limit)
    ).all()
    items = [
        SearchDeviceItem(
            id=device.id,
            label=device.host_name,
            hostname=device.host_name,
            serial=device.serial_number,
            status=device.status,
            rack_id=device.rack_id,
            rack_name=rack_name,
            position_u=device.position_u,
        )
        for device, rack_name in rows
    ]
    return DeviceSearchGroup(count=count, truncated=count > limit, items=items)


def _cabinets(session: Session, q: str, limit: int) -> CabinetSearchGroup:
    base = (
        select(RackRow.id)
        .where(RackRow.deleted_at.is_(None), contains(RackRow.name, q))
    )
    count = _count(session, base)
    rows = session.exec(
        select(RackRow, RackRowRow.name, HallRow.name)
        .join(RackRowRow, RackRowRow.id == RackRow.row_id)
        .join(HallRow, HallRow.id == RackRow.hall_id)
        .where(RackRow.deleted_at.is_(None), contains(RackRow.name, q))
        .order_by(func.lower(RackRow.name), RackRow.id)
        .limit(limit)
    ).all()
    items = [
        SearchCabinetItem(
            id=rack.id,
            label=rack.name,
            name=rack.name,
            row_id=rack.row_id,
            row_name=row_name,
            hall_id=rack.hall_id,
            hall_name=hall_name,
        )
        for rack, row_name, hall_name in rows
    ]
    return CabinetSearchGroup(count=count, truncated=count > limit, items=items)


def _rows(session: Session, q: str, limit: int) -> RowSearchGroup:
    base = select(RackRowRow.id).where(contains(RackRowRow.name, q))
    count = _count(session, base)
    rows = session.exec(
        select(RackRowRow, HallRow.id, HallRow.name, SiteRow.id, SiteRow.name)
        .join(HallRow, HallRow.id == RackRowRow.hall_id)
        .join(SiteRow, SiteRow.id == HallRow.site_id)
        .where(contains(RackRowRow.name, q))
        .order_by(func.lower(RackRowRow.name), RackRowRow.id)
        .limit(limit)
    ).all()
    items = [
        SearchRowItem(
            id=row.id,
            label=row.name,
            name=row.name,
            hall_id=hall_id,
            hall_name=hall_name,
            site_id=site_id,
            site_name=site_name,
        )
        for row, hall_id, hall_name, site_id, site_name in rows
    ]
    return RowSearchGroup(count=count, truncated=count > limit, items=items)


def _halls(session: Session, q: str, limit: int) -> HallSearchGroup:
    base = select(HallRow.id).where(contains(HallRow.name, q))
    count = _count(session, base)
    rows = session.exec(
        select(HallRow, SiteRow.id, SiteRow.name)
        .join(SiteRow, SiteRow.id == HallRow.site_id)
        .where(contains(HallRow.name, q))
        .order_by(func.lower(HallRow.name), HallRow.id)
        .limit(limit)
    ).all()
    items = [
        SearchPlaceItem(
            id=hall.id,
            label=hall.name,
            name=hall.name,
            site_id=site_id,
            site_name=site_name,
        )
        for hall, site_id, site_name in rows
    ]
    return HallSearchGroup(count=count, truncated=count > limit, items=items)


def build_search(session: Session, q: str, limit: int, now: datetime) -> HomeSearch:
    """Return grouped, capped hits for q. `limit` is the cap per group."""
    limit = limit or SEARCH_DEFAULT_LIMIT
    return HomeSearch(
        query=q,
        generated_at=iso_z(now),
        groups=[
            _devices(session, q, limit),
            _cabinets(session, q, limit),
            _rows(session, q, limit),
            _halls(session, q, limit),
        ],
        parked=[DCREQS_SEARCH_PARKED],
    )
