"""Cabinet profiles (ADMIN_INPUT_PLAN rev 3, MIGRATION_SPEC_CABINET_PROFILES.md §3): admin-only writes,
reads for every signed-in role. draft -> published -> retired -> (un-retire) published. Optional images."""
import re
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func
from sqlalchemy.exc import DataError, IntegrityError
from sqlmodel import Session, or_, select

from app.db import get_session
from app.modules.audit.service import record_audit
from app.modules.auth.deps import ADMIN, get_current_user
from app.modules.cabinet_profiles.models import CabinetProfileImageRow as Img, CabinetProfileRow as P
from app.modules.cabinet_profiles.schemas import CabinetProfileEvent, CabinetProfile, CabinetProfileCreate, CabinetProfileUpdate, CabinetCloneIn
from app.modules.history.service import new_change_set
from app.modules.images import service as img_service
from app.modules.images.router import ImageMeta, upload_limiter
from app.pagination import Pagination, contains, paginate
from app.settings import get_settings
from app.timestamps import as_utc as _as_utc


def as_utc(v):
    """Naive (SQLite) -> UTC; aware (Postgres, session time zone) -> converted to UTC."""
    v = _as_utc(v)
    return v.astimezone(UTC) if v is not None else None

router = APIRouter(prefix="/cabinet-profiles", tags=["cabinet-profiles"], dependencies=[Depends(get_current_user)])
images_router = APIRouter(tags=["cabinet-profiles"], dependencies=[Depends(get_current_user)])
Face = Literal["front", "rear"]
REQUIRED = ("manufacturer", "model", "name", "u_height", "width_mm", "height_mm", "depth_mm", "rack_unit_width")


def _err(status_code: int, code: str, message: str, **extra) -> HTTPException:
    return HTTPException(status_code, {"code": code, "message": message, **extra})


def _actor(session: Session) -> str | None:
    return getattr(session.info.get("user"), "email", None)


def missing_fields(p: P) -> list[str]:
    return [f for f in REQUIRED if getattr(p, f) in (None, "")]


def image_url(pid: int, face: str, sha: str, variant: str = "original") -> str:
    return f"/cabinet-profile-images/{pid}/{face}?v={sha[:16]}" + (f"&variant={variant}" if variant != "original" else "")


def _refs(session: Session, ids) -> dict:
    ids = [i for i in ids if i is not None]
    if not ids:
        return {}
    rows = session.exec(select(Img.cabinet_profile_id, Img.face, Img.variant, Img.sha256, Img.width_px, Img.height_px)
                        .where(Img.cabinet_profile_id.in_(ids))).all()
    by = {(p, f, v): (sha, w, h) for p, f, v, sha, w, h in rows}
    out = {}
    for (p, f, v), (sha, w, h) in by.items():
        if v == "original":
            thumb, tex = by.get((p, f, "thumb"), (sha,))[0], by.get((p, f, "tex"))
            out[(p, f)] = {"url": image_url(p, f, sha), "thumb_url": image_url(p, f, thumb, "thumb"),
                           "tex_url": image_url(p, f, tex[0], "tex") if tex else image_url(p, f, sha),
                           "width_px": w, "height_px": h, "etag": f'"{sha}"'}
    return out


TS = ("created_at", "updated_at", "published_at", "retired_at")


def updated_by_map(session: Session, ids) -> dict[int, str | None]:
    """Latest audit actor (email) per cabinet profile: one query, no stored column."""
    from app.modules.audit.models import AuditEventRow as A
    from app.modules.auth.models import UserRow
    ids = [i for i in ids if i is not None]
    if not ids:
        return {}
    last = (select(A.entity_id, func.max(A.id).label("mid")).where(A.entity_type == "cabinet_profile",
                                                                  A.entity_id.in_(ids)).group_by(A.entity_id).subquery())
    rows = session.exec(select(last.c.entity_id, UserRow.email).join(A, A.id == last.c.mid)
                        .join(UserRow, UserRow.id == A.actor_user_id, isouter=True)).all()
    return {eid: email for eid, email in rows}


def out(session: Session, profiles: list[P]) -> list[CabinetProfile]:
    refs = _refs(session, [p.id for p in profiles])
    who = updated_by_map(session, [p.id for p in profiles])
    res = []
    for p in profiles:
        miss = missing_fields(p)
        d = p.model_dump()
        d.update({k: as_utc(d[k]) for k in TS})  # SQLite hands back naive UTC; always send an offset
        d["updated_by"] = who.get(p.id)
        res.append(CabinetProfile.model_validate({
            **d, "readiness": {"ready": not miss, "missing": miss},
            "front_image": refs.get((p.id, "front")), "rear_image": refs.get((p.id, "rear"))}))
    return res


def _get(session: Session, pid: int) -> P:
    p = session.get(P, pid)
    if p is None:
        raise HTTPException(404, "Cabinet profile not found")
    return p


def _name_taken(session: Session, manufacturer: str, model: str, name: str, exclude_id: int | None = None) -> None:
    stmt = select(P.id).where(func.lower(P.manufacturer) == manufacturer.lower(), func.lower(P.model) == model.lower(),
                              func.lower(P.name) == name.lower())
    if exclude_id is not None:
        stmt = stmt.where(P.id != exclude_id)
    with session.no_autoflush:
        existing = session.exec(stmt).first()
    if existing is not None:
        raise _err(409, "cabinet_profile_name_taken", "A cabinet profile with this manufacturer, model and name "
                   "already exists (names are compared ignoring case)", existing_id=existing)


INT_MAX = 2147483647  # Postgres INTEGER; checked in the API so SQLite rejects the same values
WEIGHT_MAX = 999999.99  # NUMERIC(8,2)
INT_MM = ("width_mm", "height_mm", "depth_mm", "usable_width_mm", "usable_depth_mm", "rail_depth_min_mm",
          "rail_depth_max_mm")


def _check_dims(p: P) -> None:
    """Column range (identical on SQLite and Postgres) + cross-field rules, the same as the DB CHECKs."""
    too_big = [f for f in INT_MM if getattr(p, f) is not None and getattr(p, f) > INT_MAX]
    if p.weight_capacity_kg is not None and float(p.weight_capacity_kg) > WEIGHT_MAX:
        too_big.append("weight_capacity_kg")
    if too_big:
        raise _err(422, "invalid_dimension", f"Too large to store (sizes up to {INT_MAX} mm, weight up to "
                   f"{WEIGHT_MAX} kg)", fields=too_big)
    bad = []
    if p.usable_width_mm is not None and p.width_mm is not None and p.usable_width_mm > p.width_mm:
        bad.append("usable_width_mm")
    if p.usable_depth_mm is not None and p.depth_mm is not None and p.usable_depth_mm > p.depth_mm:
        bad.append("usable_depth_mm")
    if p.rail_depth_min_mm is not None and p.rail_depth_max_mm is not None and p.rail_depth_min_mm > p.rail_depth_max_mm:
        bad.append("rail_depth_min_mm")
    if p.rail_depth_max_mm is not None and p.depth_mm is not None and p.rail_depth_max_mm > p.depth_mm:
        bad.append("rail_depth_max_mm")
    if bad:
        raise _err(422, "invalid_dimension", "Usable sizes and rail depths must fit inside the outer size, and the "
                   "minimum rail depth can't exceed the maximum", fields=bad)


def _commit(session: Session, flush_only: bool = False) -> None:
    try:
        session.flush() if flush_only else session.commit()
    except IntegrityError as exc:  # race on the case-insensitive unique, or a CHECK backstop
        session.rollback()
        if "manufacturer_model_name" in str(exc.orig) or "UNIQUE" in str(exc.orig).upper():
            raise _err(409, "cabinet_profile_name_taken", "A cabinet profile with this manufacturer, model and "
                       "name already exists (names are compared ignoring case)") from None
        raise _err(422, "invalid_dimension", "The values break a cabinet profile rule") from None
    except DataError:  # PG: beyond the column type (INT, or NUMERIC(8,2) = 999,999.99 kg)
        session.rollback()
        raise _err(422, "invalid_dimension", "A value is too large to store") from None


def _event(session: Session, action: str, p: P, before: dict | None, after: dict, note: str) -> None:
    cs = new_change_set(session, "api", note=note)
    record_audit(session, None, f"cabinet_profile.{action}", "cabinet_profile", p.id, before=before,
                 after={**after, "change_set_id": cs.id})


@router.get("", response_model=list[CabinetProfile])
def list_cabinet_profiles(response: Response, status: Literal["draft", "published", "retired"] | None = None,
                          q: str | None = Query(None, max_length=100, description="Search manufacturer/model/name"),
                          page: Pagination = Depends(), session: Session = Depends(get_session)):
    stmt = select(P)
    if status:
        stmt = stmt.where(P.status == status)
    if q:
        stmt = stmt.where(or_(contains(P.manufacturer, q), contains(P.model, q), contains(P.name, q)))
    return out(session, paginate(session, stmt, page, response, P.id))


@router.post("", dependencies=[Depends(ADMIN)], response_model=CabinetProfile, status_code=201)
def create_cabinet_profile(payload: CabinetProfileCreate, session: Session = Depends(get_session)):
    """Create a draft (may be incomplete). Lengths in mm, or inches with "unit": "in"."""
    p = P(**payload.model_dump(), created_by=_actor(session))
    _check_dims(p)
    _name_taken(session, p.manufacturer, p.model, p.name)
    session.add(p)
    _commit(session, flush_only=True)
    new_change_set(session, "api", note=f"cabinet profile {p.id} create")
    _commit(session)
    session.refresh(p)
    return out(session, [p])[0]


@router.get("/{profile_id}", response_model=CabinetProfile)
def get_cabinet_profile(profile_id: int, session: Session = Depends(get_session)):
    return out(session, [_get(session, profile_id)])[0]


@router.patch("/{profile_id}", dependencies=[Depends(ADMIN)], response_model=CabinetProfile)
def update_cabinet_profile(profile_id: int, payload: CabinetProfileUpdate, session: Session = Depends(get_session)):
    """Drafts and published profiles are editable; a published one can't be made incomplete (422
    cabinet_profile_incomplete). Retired: 409 cabinet_profile_retired (un-retire first)."""
    p = _get(session, profile_id)
    if p.status == "retired":
        raise _err(409, "cabinet_profile_retired", "A retired profile is read-only; un-retire it or clone it")
    if payload.expected_updated_at is not None and as_utc(payload.expected_updated_at) != as_utc(p.updated_at):
        raise _err(409, "version_conflict", "The profile changed since you loaded it; reload and retry",
                   current_updated_at=as_utc(p.updated_at).isoformat(),
                   updated_by=updated_by_map(session, [p.id]).get(p.id))
    changes = payload.model_dump(exclude_unset=True)
    for k in ("manufacturer", "model", "name"):
        if k in changes and changes[k] is None:
            raise _err(422, "cabinet_profile_incomplete", f"{k} can't be empty", missing=[k])
    for k, v in changes.items():
        setattr(p, k, v)
    _check_dims(p)
    if p.status == "published" and missing_fields(p):
        raise _err(422, "cabinet_profile_incomplete", "A published profile must stay complete",
                   missing=missing_fields(p))
    if {"manufacturer", "model", "name"} & set(changes):
        _name_taken(session, p.manufacturer, p.model, p.name, exclude_id=p.id)
    session.add(p)
    if session.is_modified(p):
        _commit(session, flush_only=True)
        new_change_set(session, "api", note=f"cabinet profile {p.id} update")
    _commit(session)
    session.refresh(p)
    return out(session, [p])[0]


@router.delete("/{profile_id}", dependencies=[Depends(ADMIN)], status_code=204)
def delete_cabinet_profile(profile_id: int, session: Session = Depends(get_session)):
    """Hard delete when nothing references it (images cascade). A newer version superseding it -> 409
    cabinet_profile_in_use (reason superseded). Racks will also count once cabinets link to profiles."""
    p = _get(session, profile_id)
    newer = session.exec(select(P.id).where(P.supersedes_cabinet_profile_id == p.id)).first()
    if newer is not None:
        raise _err(409, "cabinet_profile_in_use", "A newer version supersedes this profile; delete that one first "
                   "or retire this one", reason="superseded", superseded_by=newer)
    new_change_set(session, "api", note=f"cabinet profile {p.id} delete")
    for img in session.exec(select(Img).where(Img.cabinet_profile_id == p.id)).all():
        session.delete(img)
    session.delete(p)  # AUDITED listener writes the full snapshot (cabinet_profile.delete)
    session.commit()
    return Response(status_code=204)


def _transition(session: Session, pid: int, allowed_from: str, to: str, action: str) -> CabinetProfile:
    p = _get(session, pid)
    if p.status == to:
        return out(session, [p])[0]  # idempotent
    if p.status != allowed_from:
        raise _err(422, "invalid_status_transition", f"A {p.status} profile can't be {action}d",
                   status=p.status, to=to)
    if to == "published" and missing_fields(p):
        raise _err(422, "cabinet_profile_incomplete", "This profile is missing required fields",
                   missing=missing_fields(p))
    before = {"status": p.status}
    now, actor = datetime.now(UTC), _actor(session)
    p.status = to
    if action == "publish":
        p.published_at, p.published_by = now, actor
    elif action == "retire":
        p.retired_at, p.retired_by = now, actor
    else:  # unretire -> published (it passed readiness before; the CHECK kept it ready)
        p.retired_at = p.retired_by = None
    session.add(p)
    session.flush()
    _event(session, action, p, before, {"status": to}, f"cabinet profile {p.id} {action}")
    session.commit()
    session.refresh(p)
    return out(session, [p])[0]


_DT = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$")


def iso_utc(v) -> str | None:
    """Any datetime (or datetime-looking string, incl. old naive audit rows = UTC) -> 'YYYY-MM-DDTHH:MM:SS[.ffffff]+00:00'."""
    if v is None:
        return None
    if isinstance(v, str):
        v = datetime.fromisoformat(v.replace("Z", "+00:00"))
    return as_utc(v).isoformat()


def _norm(obj):
    if isinstance(obj, dict):
        return {k: _norm(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_norm(v) for v in obj]
    if isinstance(obj, str) and _DT.match(obj):
        try:
            return iso_utc(obj)
        except ValueError:
            return obj
    return obj


@router.get("/{profile_id}/history", dependencies=[Depends(ADMIN)], response_model=list[CabinetProfileEvent])
def cabinet_profile_history(profile_id: int, response: Response, page: Pagination = Depends(),
                            session: Session = Depends(get_session)):
    """Admin only (same as /audit-events): this profile's audit events, newest first. Works after delete too."""
    import json
    from app.modules.audit.models import AuditEventRow as A
    from app.modules.auth.models import UserRow
    stmt = (select(A, UserRow.email).join(UserRow, UserRow.id == A.actor_user_id, isouter=True)
            .where(A.entity_type == "cabinet_profile", A.entity_id == profile_id))
    total = session.exec(select(func.count()).select_from(stmt.subquery())).one()
    response.headers["X-Total-Count"] = str(total)
    rows = session.exec(stmt.order_by(A.id.desc()).offset(page.offset).limit(page.limit)).all()
    load = lambda t: _norm(json.loads(t)) if t else None  # noqa: E731
    return [CabinetProfileEvent(id=a.id, occurred_at=iso_utc(a.occurred_at), action=a.action, actor_email=email,
                                before=load(a.before_json), after=load(a.after_json)) for a, email in rows]


@router.post("/{profile_id}/publish", dependencies=[Depends(ADMIN)], response_model=CabinetProfile)
def publish_cabinet_profile(profile_id: int, session: Session = Depends(get_session)):
    """draft -> published when complete (422 cabinet_profile_incomplete with missing[]). Images aren't required."""
    return _transition(session, profile_id, "draft", "published", "publish")


@router.post("/{profile_id}/retire", dependencies=[Depends(ADMIN)], response_model=CabinetProfile)
def retire_cabinet_profile(profile_id: int, session: Session = Depends(get_session)):
    """published -> retired (no new cabinets). A draft can't be retired (delete it instead)."""
    return _transition(session, profile_id, "published", "retired", "retire")


@router.post("/{profile_id}/unretire", dependencies=[Depends(ADMIN)], response_model=CabinetProfile)
def unretire_cabinet_profile(profile_id: int, session: Session = Depends(get_session)):
    """retired -> published (never back to draft)."""
    p = _get(session, profile_id)
    if p.status == "published":
        raise _err(422, "invalid_status_transition", "Only a retired profile can be un-retired", status=p.status,
                   to="published")
    return _transition(session, profile_id, "retired", "published", "unretire")


@router.post("/{profile_id}/clone", dependencies=[Depends(ADMIN)], response_model=CabinetProfile, status_code=201)
def clone_cabinet_profile(profile_id: int, payload: CabinetCloneIn | None = None, session: Session = Depends(get_session)):
    """New draft: version+1, supersedes the source, all fields and every image row copied (new ids, same bytes)."""
    src = _get(session, profile_id)
    fields = src.model_dump(exclude={"id", "status", "version", "supersedes_cabinet_profile_id", "created_at",
                                     "updated_at", "created_by", "published_at", "published_by", "retired_at",
                                     "retired_by", "name"})
    if payload and payload.name:
        name = payload.name
        _name_taken(session, src.manufacturer, src.model, name)  # explicit name taken -> 409
    else:  # first free of '<name> (copy)', '<name> (copy 2)', ... (case-insensitive, like the unique index)
        with session.no_autoflush:
            used = {n.lower() for n in session.exec(select(P.name).where(
                func.lower(P.manufacturer) == src.manufacturer.lower(), func.lower(P.model) == src.model.lower())).all()}
        name, n = f"{src.name} (copy)", 2
        while name.lower() in used:
            name, n = f"{src.name} (copy {n})", n + 1
    actor = _actor(session)
    new = P(**fields, name=name, status="draft", version=src.version + 1, supersedes_cabinet_profile_id=src.id,
            created_by=actor)
    session.add(new)
    session.flush()
    imgs = session.exec(select(Img).where(Img.cabinet_profile_id == src.id)).all()
    for img in imgs:
        data = img.model_dump(exclude={"id", "cabinet_profile_id", "created_at", "updated_at", "version", "uploaded_by"})
        session.add(Img(**data, cabinet_profile_id=new.id, version=1, uploaded_by=actor))
    _event(session, "clone", new, None, {"source_id": src.id, "new_id": new.id, "image_count": len(imgs)},
           f"cabinet profile {src.id} clone -> {new.id}")
    _commit(session)
    session.refresh(new)
    return out(session, [new])[0]


# ---- images (optional; same pipeline and limits as device-profile images) ----
def _meta(session: Session, pid: int) -> list[ImageMeta]:
    rows = session.exec(select(Img.face, Img.variant, Img.content_type, Img.byte_size, Img.width_px, Img.height_px,
                               Img.sha256, Img.version).where(Img.cabinet_profile_id == pid)).all()
    shas = {(r.face, r.variant): r.sha256 for r in rows}
    return [ImageMeta(face=r.face, content_type=r.content_type, byte_size=r.byte_size, width_px=r.width_px,
                      height_px=r.height_px, sha256=r.sha256, version=r.version, etag=f'"{r.sha256}"',
                      url=image_url(pid, r.face, r.sha256),
                      thumb_url=image_url(pid, r.face, shas[(r.face, "thumb")], "thumb") if (r.face, "thumb") in shas else None,
                      tex_url=image_url(pid, r.face, shas[(r.face, "tex")], "tex") if (r.face, "tex") in shas else None)
            for r in rows if r.variant == "original"]


def _writable(p: P) -> None:
    if p.status == "retired":
        raise _err(409, "cabinet_profile_retired", "A retired profile is read-only; un-retire it or clone it")


@router.put("/{profile_id}/images/{face}", dependencies=[Depends(ADMIN)], response_model=ImageMeta,
            openapi_extra={"requestBody": {"required": True, "content": {
                t: {"schema": {"type": "string", "format": "binary"}} for t in img_service.FORMATS}}})
async def upload_cabinet_image(profile_id: int, face: Face, request: Request, response: Response,
                               session: Session = Depends(get_session)):
    """PNG/JPEG/WebP, <= 2 MiB, <= 4096 px; re-encoded without metadata; thumb (512) + tex (1024) WebP derived."""
    user = session.info.get("user")
    wait = upload_limiter.retry_after(f"user:{getattr(user, 'id', None)}", get_settings().image_uploads_per_minute, 60)
    if wait:
        raise HTTPException(429, "Too many image uploads; try again shortly", headers={"Retry-After": str(wait)})
    p = _get(session, profile_id)
    _writable(p)
    data = await img_service.read_capped(request)
    from starlette.concurrency import run_in_threadpool
    result = await run_in_threadpool(img_service.process_bounded, data, request.headers.get("content-type"))
    existing = {r.variant: r for r in session.exec(select(Img).where(Img.cabinet_profile_id == p.id,
                                                                     Img.face == face)).all()}
    orig = existing.get("original")
    if_match = request.headers.get("if-match")
    if if_match is not None and (orig is None or if_match.strip() not in (f'"{orig.sha256}"', orig.sha256, "*")):
        raise HTTPException(412, {"code": "image_changed", "message": "The image changed since you loaded it"})
    actor = _actor(session)
    for variant, info in result.items():
        row = existing.get(variant)
        if row is None:
            session.add(Img(cabinet_profile_id=p.id, face=face, variant=variant, uploaded_by=actor, **info))
        else:
            for k, v in info.items():
                setattr(row, k, v)
            row.version += 1
            row.uploaded_by = actor
    session.flush()
    o = result["original"]
    _event(session, "image.put", p, {"face": face, "sha256": orig.sha256} if orig else None,
           {"face": face, "sha256": o["sha256"], "byte_size": o["byte_size"], "width_px": o["width_px"],
            "height_px": o["height_px"]}, f"cabinet profile {p.id} {face} image")
    session.commit()
    response.status_code = 200 if orig else 201
    return next(m for m in _meta(session, p.id) if m.face == face)


@router.delete("/{profile_id}/images/{face}", dependencies=[Depends(ADMIN)], status_code=204)
def delete_cabinet_image(profile_id: int, face: Face, session: Session = Depends(get_session)):
    p = _get(session, profile_id)
    _writable(p)
    rows = session.exec(select(Img).where(Img.cabinet_profile_id == p.id, Img.face == face)).all()
    if not rows:
        raise HTTPException(404, "Image not found")
    orig = next((r for r in rows if r.variant == "original"), rows[0])
    _event(session, "image.delete", p, {"face": face, "sha256": orig.sha256, "byte_size": orig.byte_size},
           {"face": face, "sha256": None}, f"cabinet profile {p.id} {face} image delete")
    for r in rows:
        session.delete(r)
    session.commit()
    return Response(status_code=204)


@images_router.get("/cabinet-profile-images/{profile_id}/{face}", response_class=Response,
                   responses={200: {"content": {t: {} for t in img_service.FORMATS}}, 304: {}, 404: {}})
def get_cabinet_image(profile_id: int, face: Face, request: Request,
                      variant: Literal["original", "thumb", "tex"] = Query("original"),
                      v: str | None = Query(None, max_length=64, description="Content version; makes the URL immutable"),
                      session: Session = Depends(get_session)):
    head = session.exec(select(Img.id, Img.sha256, Img.content_type, Img.updated_at).where(
        Img.cabinet_profile_id == profile_id, Img.face == face, Img.variant == variant)).first()
    if head is None:
        raise HTTPException(404, "Image not found")
    etag = f'"{head.sha256}"'
    current = bool(v) and len(v) >= 16 and head.sha256.startswith(v.lower())
    headers = {"ETag": etag, "X-Content-Type-Options": "nosniff",
               "Cache-Control": "private, max-age=31536000, immutable" if current else "private, max-age=300, must-revalidate",
               "Content-Security-Policy": "default-src 'none'; sandbox"}
    if head.updated_at is not None:
        headers["Last-Modified"] = head.updated_at.strftime("%a, %d %b %Y %H:%M:%S GMT")
    if etag in [t.strip() for t in request.headers.get("if-none-match", "").split(",")]:
        return Response(status_code=304, headers=headers)
    data = session.exec(select(Img.data).where(Img.id == head.id)).one()
    ext = img_service.FORMATS[head.content_type].lower().replace("jpeg", "jpg")
    headers["Content-Disposition"] = f'inline; filename="cabinet-profile-{profile_id}-{face}.{ext}"'
    return Response(content=bytes(data), media_type=head.content_type, headers=headers)
