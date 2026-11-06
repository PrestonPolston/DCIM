"""Safety-net audit for locations, device types and profiles: one event per insert/update/delete.

Device changes are audited explicitly by the device lifecycle (install/move/decom/...).
"""
from sqlalchemy import event, inspect
from sqlmodel import Session

from app.modules.audit.service import record_audit
from app.modules.device_types.models import DeviceTypeProfileRow, DeviceTypeRow
from app.modules.directory.models import (
    ContactRow, GroupRow, ProjectContactRow, ProjectReferenceRow, ProjectRow, VendorRow,
)
from app.modules.locations.models import HallRow, RackRow, RackRowRow, SiteRow
from app.modules.connections.models import DevicePortRow
from app.modules.cabinet_profiles.models import CabinetProfileRow

AUDITED = {
    SiteRow: ("location", "site"), HallRow: ("location", "hall"), RackRowRow: ("location", "row"),
    RackRow: ("location", "rack"), DeviceTypeRow: ("device_type", "device_type"),
    DeviceTypeProfileRow: ("device_type", "profile"), GroupRow: ("directory", "group"),
    VendorRow: ("directory", "vendor"), ContactRow: ("directory", "contact"), ProjectRow: ("directory", "project"),
    ProjectReferenceRow: ("directory", "project_reference"), ProjectContactRow: ("directory", "project_contact"),
    DevicePortRow: ("connection", "port"), CabinetProfileRow: ("cabinet_profile", "cabinet_profile"),
}
SKIP = {"created_at", "updated_at"}


def _changes(obj) -> tuple[dict, dict]:
    before, after = {}, {}
    for attr in inspect(obj).attrs:
        if attr.key in SKIP:
            continue
        hist = attr.history
        if hist.has_changes():
            before[attr.key] = hist.deleted[0] if hist.deleted else None
            after[attr.key] = hist.added[0] if hist.added else None
    return before, after


def _snapshot(obj) -> dict:
    return {k: v for k, v in obj.model_dump().items() if k not in SKIP}


@event.listens_for(Session, "after_flush")
def _audit_after_flush(session, _flush_context):
    if session.info.get("user") is None:
        return  # scripts/migrations/tests without a request
    events = []
    for obj in session.new:
        if type(obj) in AUDITED:
            events.append((obj, "create", None, _snapshot(obj)))
    for obj in session.dirty:
        if type(obj) in AUDITED and session.is_modified(obj, include_collections=False):
            before, after = _changes(obj)
            if before or after:
                action = "soft_delete" if after.get("deleted_at") else "update"
                events.append((obj, action, before, after))
    for obj in session.deleted:
        if type(obj) in AUDITED:
            events.append((obj, "delete", _snapshot(obj), None))
    for obj, action, before, after in events:
        prefix, kind = AUDITED[type(obj)]
        name = f"{prefix}.{action}" if prefix == kind else f"{prefix}.{kind}.{action}"
        record_audit(session, None, name, kind, getattr(obj, "id", None), before=before, after=after)
