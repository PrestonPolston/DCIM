"""Build the role-aware GET /home/summary payload. One `now` per request; no N+1."""
from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlmodel import Session, select

from app.modules.device_types.lifecycle import readiness_map, usability
from app.modules.device_types.models import DeviceTypeProfileRow as P, DeviceTypeRow as T
from app.modules.devices.models import DeviceRow
from app.modules.home.constants import (
    HOME_LIST_LIMIT,
    RECENTLY_RETIRED_DAYS,
    STALE_DRAFT_DAYS,
    UNPOSITIONED_DEVICE_LIMIT,
)
from app.modules.home.schemas import (
    AdminSection,
    DeviceIssuesTile,
    HomeSummary,
    MyWork,
    NeedsReviewItem,
    NeedsReviewList,
    ParkedTile,
    ProfileHealthTile,
    RecentlyChangedItem,
    RecentlyChangedList,
    RecentlyRetiredItem,
    RecentlyRetiredList,
    StaleDraftItem,
    StaleDraftsList,
    StatusCounts,
    UnpositionedDeviceItem,
    UnpositionedList,
)
from app.timestamps import as_utc, iso_z

LIVE_DEVICE_STATUSES = ("install", "active")

JOBS_PARKED = ParkedTile(key="jobs", message="Needs jobs/DCREQ logic.")
DCREQS_PARKED = ParkedTile(key="dcreqs", message="Needs jobs/DCREQ logic.")
HELD_IMPORTS_PARKED = ParkedTile(
    key="held_imports", message="Held ePIF import rows are not in the API yet.")
WORKLOAD_PARKED = ParkedTile(key="workload", message="Needs jobs/DCREQ logic.")
POWER_ASSIGNMENT_PARKED = ParkedTile(
    key="needs_power_assignment",
    message="Needs device_psu_assignments; devices.power_assignment is free text only.")
PORT_CONFLICTS_PARKED = ParkedTile(
    key="port_conflicts",
    message="Port conflicts are refused at write time; there is no stored flag.")
POWER_MISMATCHES_PARKED = ParkedTile(
    key="open_power_mismatches",
    message="The power_mismatches table and route are not built.")


def _display_name(manufacturer: str, model: str, name: str) -> str:
    return f"{manufacturer} {model} · {name}"


def _capped(count: int, limit: int) -> bool:
    return count > limit


def _my_work() -> MyWork:
    return MyWork(jobs=JOBS_PARKED, dcreqs=DCREQS_PARKED, held_imports=HELD_IMPORTS_PARKED)


def _status_counts(session: Session) -> StatusCounts:
    rows = session.exec(select(P.status, func.count()).group_by(P.status)).all()
    counts = {status: n for status, n in rows}
    return StatusCounts(draft=counts.get("draft", 0), published=counts.get("published", 0),
                        retired=counts.get("retired", 0))


def _needs_review(session: Session) -> NeedsReviewList:
    published = session.exec(
        select(P, T.manufacturer, T.name).join(T, T.id == P.device_type_id).where(P.status == "published")
    ).all()
    profiles = [p for p, _, _ in published]
    ready = readiness_map(session, profiles)
    items: list[NeedsReviewItem] = []
    issue_counts: Counter[str] = Counter()
    for p, manufacturer, model in published:
        usable, issues = usability(p.status, ready[p.id])
        if usable:
            continue
        for issue in issues:
            issue_counts[issue] += 1
        items.append(NeedsReviewItem(
            id=p.id, name=_display_name(manufacturer, model, p.name),
            usable_issue=(issues or [None])[0], usable_issues=issues,
        ))
    # Worst first: more issues, then first issue priority already encoded in usable_issues order.
    items.sort(key=lambda i: (-len(i.usable_issues), i.usable_issues, i.id))
    limit = HOME_LIST_LIMIT
    return NeedsReviewList(
        count=len(items), truncated=_capped(len(items), limit), items=items[:limit],
        by_issue={"rear_image_missing": issue_counts.get("rear_image_missing", 0),
                  "orientation_missing": issue_counts.get("orientation_missing", 0)},
    )


def _stale_drafts(session: Session, now: datetime) -> StaleDraftsList:
    cutoff = now - timedelta(days=STALE_DRAFT_DAYS)
    cond = (P.status == "draft") & (P.updated_at <= cutoff)
    count = session.exec(select(func.count()).select_from(P).where(cond)).one()
    rows = session.exec(
        select(P, T.manufacturer, T.name).join(T, T.id == P.device_type_id).where(cond)
        .order_by(P.updated_at, P.id).limit(HOME_LIST_LIMIT)
    ).all()
    items = [StaleDraftItem(id=p.id, name=_display_name(mfr, model, p.name),
                            updated_at=iso_z(p.updated_at))
             for p, mfr, model in rows]
    return StaleDraftsList(count=count, truncated=_capped(count, HOME_LIST_LIMIT), items=items)


def _recently_retired(session: Session, now: datetime) -> RecentlyRetiredList:
    cutoff = now - timedelta(days=RECENTLY_RETIRED_DAYS)
    cond = (P.status == "retired") & (P.retired_at.is_not(None)) & (P.retired_at >= cutoff)
    count = session.exec(select(func.count()).select_from(P).where(cond)).one()
    rows = session.exec(
        select(P, T.manufacturer, T.name).join(T, T.id == P.device_type_id).where(cond)
        .order_by(P.retired_at.desc(), P.id).limit(HOME_LIST_LIMIT)
    ).all()
    items = [RecentlyRetiredItem(id=p.id, name=_display_name(mfr, model, p.name),
                                 retired_at=iso_z(p.retired_at))
             for p, mfr, model in rows]
    return RecentlyRetiredList(count=count, truncated=_capped(count, HOME_LIST_LIMIT), items=items)


def _recently_changed(session: Session) -> RecentlyChangedList:
    count = session.exec(select(func.count()).select_from(P)).one()
    rows = session.exec(
        select(P, T.manufacturer, T.name).join(T, T.id == P.device_type_id)
        .order_by(P.updated_at.desc(), P.id).limit(HOME_LIST_LIMIT)
    ).all()
    items = [RecentlyChangedItem(
        id=p.id, name=_display_name(mfr, model, p.name), status=p.status,
        updated_at=iso_z(p.updated_at), published_at=iso_z(p.published_at),
        retired_at=iso_z(p.retired_at),
    ) for p, mfr, model in rows]
    return RecentlyChangedList(count=count, truncated=_capped(count, HOME_LIST_LIMIT), items=items)


def _no_position(session: Session) -> UnpositionedList:
    cond = (
        DeviceRow.deleted_at.is_(None)
        & DeviceRow.status.in_(LIVE_DEVICE_STATUSES)
        & DeviceRow.rack_id.is_(None)
    )
    count = session.exec(select(func.count()).select_from(DeviceRow).where(cond)).one()
    rows = session.exec(
        select(DeviceRow).where(cond).order_by(DeviceRow.updated_at.desc(), DeviceRow.id)
        .limit(UNPOSITIONED_DEVICE_LIMIT)
    ).all()
    items = [UnpositionedDeviceItem(
        id=d.id, hostname=d.host_name, status=d.status, updated_at=iso_z(d.updated_at),
    ) for d in rows]
    return UnpositionedList(
        count=count, truncated=_capped(count, UNPOSITIONED_DEVICE_LIMIT), items=items)


def _admin(session: Session, now: datetime) -> AdminSection:
    return AdminSection(
        profile_health=ProfileHealthTile(
            by_status=_status_counts(session),
            needs_review=_needs_review(session),
            stale_drafts=_stale_drafts(session, now),
            recently_retired=_recently_retired(session, now),
            recently_changed=_recently_changed(session),
        ),
        device_issues=DeviceIssuesTile(
            no_position=_no_position(session),
            needs_power_assignment=POWER_ASSIGNMENT_PARKED,
            port_conflicts=PORT_CONFLICTS_PARKED,
            open_power_mismatches=POWER_MISMATCHES_PARKED,
        ),
        workload=WORKLOAD_PARKED,
    )


def build_summary(session: Session, role: str, now: datetime) -> HomeSummary:
    """`now` must be a single UTC instant for the whole request."""
    now = as_utc(now)
    payload = HomeSummary(generated_at=iso_z(now), my_work=_my_work())
    if role == "admin":
        payload.admin = _admin(session, now)
    return payload
