"""Profile template readiness and lifecycle (p1_17): draft -> published -> retired."""
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlmodel import Session, select

from app.modules.audit.service import record_audit
from app.modules.device_types.models import DeviceTypeProfileRow, DeviceTypeRow

REQUIRED = ("name", "asset_type", "u_height", "width_mm", "height_mm", "depth_mm", "mounting", "power_type",
            "front_image", "rear_image", "orientation")
MISSING_MESSAGES = {
    "asset_type": "The model (device type) has no asset type; set it on the model "
                  "(PATCH /device-types/{id} {asset_type}) before this profile can be published",
    "front_image": "Upload a front image",
    "rear_image": "Upload a rear image (required to publish since 2026-10-24)",
    "orientation": "Switch profiles need an orientation: port_front or power_front",
    "name": "Give the profile a name",
}
# Fields that define how a profile renders/fits; frozen once published (clone a new version instead)
TEMPLATE_FIELDS = {"width_mm", "height_mm", "depth_mm", "is_full_depth", "mounting", "power_type", "weight_kg",
                   "faces"}


def missing_fields(profile: DeviceTypeProfileRow, device_type: DeviceTypeRow | None, has_front: bool,
                   has_rear: bool = False) -> list[str]:
    out = []
    for f in REQUIRED:
        if f == "orientation":  # D58: required only for switches
            if device_type is not None and device_type.asset_type == "switch" and profile.orientation is None:
                out.append(f)
            continue
        if f == "name":
            ok = bool((profile.name or "").strip())
        elif f == "asset_type":
            ok = device_type is not None and device_type.asset_type is not None
        elif f == "u_height":
            ok = profile.u_height is not None and profile.u_height >= 1
        elif f == "front_image":
            ok = has_front
        elif f == "rear_image":
            ok = has_rear
        else:
            ok = getattr(profile, f) is not None
        if not ok:
            out.append(f)
    return out


def readiness_map(session: Session, profiles: list[DeviceTypeProfileRow]) -> dict[int, dict]:
    """{profile_id: {ready, missing}} in two queries (no image bytes loaded)."""
    from app.modules.images.models import ProfileImageRow
    ids = [p.id for p in profiles]
    if not ids:
        return {}
    type_ids = {p.device_type_id for p in profiles}
    types = {t.id: t for t in session.exec(select(DeviceTypeRow).where(DeviceTypeRow.id.in_(type_ids))).all()}
    faces = session.exec(select(ProfileImageRow.profile_id, ProfileImageRow.face).where(
        ProfileImageRow.profile_id.in_(ids), ProfileImageRow.variant == "original")).all()
    fronts = {p for p, f in faces if f == "front"}
    rears = {p for p, f in faces if f == "rear"}
    out = {}
    for p in profiles:
        missing = missing_fields(p, types.get(p.device_type_id), p.id in fronts, p.id in rears)
        out[p.id] = {"ready": not missing, "missing": missing,
                     "messages": {f: MISSING_MESSAGES.get(f, f"{f} is required") for f in missing},
                     # D54/D58: issues of an already-published profile (it stays published, just not usable)
                     "flags": usability(p.status, {"missing": missing})[1] if p.status == "published" else []}
    return out


def publish(session: Session, profile: DeviceTypeProfileRow) -> DeviceTypeProfileRow:
    if profile.status == "published":
        return profile
    if profile.status == "retired":
        raise HTTPException(409, {"code": "profile_retired", "message": "A retired profile can't be published again; "
                                  "clone it into a new version"})
    r = readiness_map(session, [profile])[profile.id]
    if not r["ready"]:
        raise HTTPException(422, {"code": "profile_not_ready", "message": "This profile is missing required fields",
                                  "missing": r["missing"], "messages": r["messages"]})
    before = {"status": profile.status}
    profile.status, profile.published_at = "published", datetime.now(UTC)
    profile.published_by = getattr(session.info.get("user"), "email", None)
    session.add(profile)
    session.flush()
    # devices flagged only because this profile was not published are fine now
    from sqlmodel import update
    from app.modules.devices.models import DeviceRow
    cleared = session.exec(update(DeviceRow).where(
        DeviceRow.profile_id == profile.id, DeviceRow.needs_review_reason == "profile_not_published")
        .values(needs_review=False, needs_review_reason=None)).rowcount
    record_audit(session, None, "profile.publish", "profile", profile.id, before=before,
                 after={"status": "published", "flags_cleared": cleared})
    return profile


def usability(status: str, readiness: dict) -> tuple[bool, list[str]]:
    """Computed live (no stored state): a profile is usable for NEW devices and profile switches when it is
    published AND its readiness is complete. A published profile that lacks something added to the rules later
    (e.g. a rear image) stays published but is not usable until fixed."""
    issues = [] if status == "published" else [f"profile_{status}"]
    missing = list(readiness.get("missing") or [])
    # D58 priority: status, then rear_image_missing, then orientation_missing, then any other gap
    missing.sort(key=lambda f: ISSUE_PRIORITY.get(f, len(ISSUE_PRIORITY)))
    issues += [f"{f}_missing" for f in missing]
    return not issues, issues


ISSUE_PRIORITY = {"rear_image": 0, "orientation": 1}


def usable_profile_ids(session: Session, profiles: list[DeviceTypeProfileRow]) -> set[int]:
    """The ONE usable rule (usability over readiness_map) as an id set, for ?usable= filters."""
    ready = readiness_map(session, profiles)
    return {p.id for p in profiles if usability(p.status, ready[p.id])[0]}


def require_usable(session: Session, profile: DeviceTypeProfileRow) -> None:
    """422 profile_not_usable for a published profile that can't take new devices (one code everywhere).
    A positive result is cached on the session (one request / one CSV file), so bulk imports stay fast."""
    cache = session.info.setdefault("usable_profiles", set())
    if profile.id in cache:
        return
    r = readiness_map(session, [profile])[profile.id]
    ok, issues = usability(profile.status, r)
    if ok:
        cache.add(profile.id)
    if not ok:
        raise HTTPException(422, {"code": "profile_not_usable",
                                  "message": f"Profile '{profile.name}' can't be used for new devices or profile "
                                             f"changes: {', '.join(issues)}",
                                  "profile_id": profile.id, "reason": issues[0], "issues": issues,
                                  "missing": r["missing"]})


def is_published(profile: DeviceTypeProfileRow | None) -> bool:
    return profile is not None and profile.status == "published"


def device_count(session: Session, profile_id: int) -> int:
    from sqlmodel import func
    from app.modules.devices.models import DeviceRow
    return session.exec(select(func.count()).select_from(DeviceRow).where(
        DeviceRow.profile_id == profile_id, DeviceRow.deleted_at.is_(None))).one()


CLONE_FIELDS = ("u_height", "width_mm", "height_mm", "depth_mm", "is_full_depth", "faces", "ports", "power",
                "model_refs", "color_hex", "airflow", "power_type", "mounting", "weight_kg", "orientation")


FLIP = {"port_front": "power_front", "power_front": "port_front"}
SUFFIX = {"port_front": " (port front)", "power_front": " (power front)"}
NAME_MAX = 128


def swap_name(session: Session, profile: DeviceTypeProfileRow, new_orientation: str | None) -> str:
    """REVIEW_ORIENTATION: replace an existing opposite suffix, add ' (power front)'/' (port front)', then
    ' 2', ' 3'... on a case-insensitive collision; cap at 128 chars (truncate the base, keep the suffix)."""
    base = profile.name
    for s in SUFFIX.values():
        if base.lower().endswith(s):
            base = base[: -len(s)]
            break
    suffix = SUFFIX.get(new_orientation, " (swapped)")
    taken = {n.lower() for n in session.exec(select(DeviceTypeProfileRow.name).where(
        DeviceTypeProfileRow.device_type_id == profile.device_type_id)).all()}
    n = 1
    while True:
        tail = suffix + ("" if n == 1 else f" {n}")
        name = base[: NAME_MAX - len(tail)] + tail
        if name.lower() not in taken:
            return name
        n += 1


def clone(session: Session, profile: DeviceTypeProfileRow, name: str | None = None,
          swap_faces: bool = False) -> DeviceTypeProfileRow:
    """Item 41: a new draft version (version+1, supersedes_profile_id) with the same fields and images.
    swap_faces (D58): front/rear images swapped, orientation flipped (NULL stays NULL), suffixed name."""
    from app.modules.images.models import ProfileImageRow
    from sqlmodel import func
    lineage_max = session.exec(select(func.max(DeviceTypeProfileRow.version)).where(
        DeviceTypeProfileRow.device_type_id == profile.device_type_id)).one() or 1
    version = max(lineage_max, profile.version) + 1
    fields = {f: getattr(profile, f) for f in CLONE_FIELDS}
    if swap_faces:
        fields["orientation"] = FLIP.get(profile.orientation)
    default_name = swap_name(session, profile, fields["orientation"]) if swap_faces else f"{profile.name} v{version}"
    new = DeviceTypeProfileRow(device_type_id=profile.device_type_id, name=name or default_name,
                               is_default=False, status="draft", version=version, supersedes_profile_id=profile.id,
                               **fields)
    session.add(new)
    from app.db import flush_or_409
    flush_or_409(session, {"code": "profile_name_conflict",
                           "message": "A profile with this name already exists for this device type"})
    imgs = session.exec(select(ProfileImageRow).where(ProfileImageRow.profile_id == profile.id)).all()
    if swap_faces:  # originals copied crosswise; derived variants regenerated from them (one place for the rules)
        from app.modules.images import service as img_service
        derived = []
        for img in imgs:
            if img.variant != "original":
                continue
            face = "rear" if img.face == "front" else "front"
            data = img.model_dump(exclude={"id", "profile_id", "created_at", "updated_at", "version", "face"})
            derived.append(ProfileImageRow(**data, profile_id=new.id, face=face))
            for variant, info in img_service.process(bytes(img.data), img.content_type).items():
                if variant != "original":
                    derived.append(ProfileImageRow(profile_id=new.id, face=face, variant=variant, **info))
        rows = derived
    else:
        rows = [ProfileImageRow(**img.model_dump(exclude={"id", "profile_id", "created_at", "updated_at", "version"}),
                                profile_id=new.id) for img in imgs]
    for row in rows:
        session.add(row)
        if row.variant == "original":  # F-3: every image change is audited (metadata only)
            record_audit(session, None, "profile_image.create", "profile", new.id, after={
                "profile_id": new.id, "face": row.face, "profile_status": "draft", "old_sha256": None,
                "new_sha256": row.sha256, "sha256": row.sha256, "byte_size": row.byte_size,
                "copied_from_profile_id": profile.id, "swap_faces": swap_faces})
    session.flush()
    record_audit(session, None, "profile.clone", "profile", new.id, after={
        "supersedes_profile_id": profile.id, "cloned_from": profile.id, "version": version,
        "swap_faces": swap_faces, "orientation": new.orientation})
    return new


def retire(session: Session, profile: DeviceTypeProfileRow) -> DeviceTypeProfileRow:
    """published -> retired: no new device may use it; devices already on it keep it (move them with adopt)."""
    if profile.status == "retired":
        return profile
    if profile.status != "published":
        raise HTTPException(409, {"code": "profile_not_published", "message": "Only a published profile can be retired"})
    profile.status, profile.retired_at = "retired", datetime.now(UTC)
    session.add(profile)
    session.flush()
    record_audit(session, None, "profile.retire", "profile", profile.id, before={"status": "published"},
                 after={"status": "retired", "device_count": device_count(session, profile.id)})
    return profile


def adopt(session: Session, target: DeviceTypeProfileRow, device_ids: list[int] | None, from_all: bool) -> list:
    """Item 41: move devices onto a published profile of the same type, re-checking fit for each.
    All-or-nothing: any conflict -> 409 listing every failing device, nothing changed."""
    from app.modules.devices import lifecycle as dev_lifecycle
    from app.modules.devices.models import DeviceRow
    from app.modules.history.service import new_change_set
    if target.status != "published":
        raise HTTPException(422, {"code": "profile_not_published", "message": "Devices can only move to a published "
                                  "profile", "profile_id": target.id, "profile_status": target.status})
    require_usable(session, target)
    stmt = select(DeviceRow).where(DeviceRow.deleted_at.is_(None), DeviceRow.profile_id != target.id)
    if from_all:
        if target.supersedes_profile_id is None:
            raise HTTPException(422, {"code": "nothing_to_adopt", "message": "all=true needs a profile that "
                                      "supersedes another; pass device_ids"})
        stmt = stmt.where(DeviceRow.profile_id == target.supersedes_profile_id)
    else:
        stmt = stmt.where(DeviceRow.id.in_(device_ids or []))
    devices = session.exec(stmt.order_by(DeviceRow.id)).all()
    if not from_all:
        found = {d.id for d in devices}
        missing = [i for i in (device_ids or []) if i not in found]
        if missing:
            raise HTTPException(404, {"code": "device_not_found", "message": "Unknown or deleted devices",
                                      "device_ids": missing})
    change_set = new_change_set(session, "api", note=f"adopt profile {target.id}")
    conflicts = []
    for d in devices:
        if d.device_type_id is not None and d.device_type_id != target.device_type_id:
            conflicts.append({"device_id": d.id, "host_name": d.host_name, "code": "profile_type_mismatch",
                              "message": "Device is of a different device type"})
            continue
        saved = (d.profile_id, d.device_type_id, d.needs_review, d.needs_review_reason)
        try:
            dev_lifecycle.update(session, d, {"profile_id": target.id}, change_set)
            session.flush()
        except HTTPException as exc:
            d.profile_id, d.device_type_id, d.needs_review, d.needs_review_reason = saved
            detail = exc.detail if isinstance(exc.detail, dict) else {"code": f"http_{exc.status_code}",
                                                                      "message": str(exc.detail)}
            conflicts.append({"device_id": d.id, "host_name": d.host_name, **detail})
    if conflicts:
        session.rollback()
        raise HTTPException(409, {"code": "adopt_conflict", "message": f"{len(conflicts)} device(s) can't use this "
                                  "profile; nothing was changed", "conflicts": conflicts})
    return devices
