from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db import get_session
from app.modules.audit.service import record_audit
from app.modules.auth.deps import TECH, get_current_user
from app.modules.device_types.models import DeviceTypeProfileRow
from app.modules.history.service import new_change_set
from app.modules.images import service
from app.modules.images.models import ProfileImageRow
from app.modules.images.refs import image_url
from app.security.ratelimit import SlidingWindow
from app.settings import get_settings

router = APIRouter(dependencies=[Depends(get_current_user)], tags=["profile-images"])
upload_limiter = SlidingWindow()
Face = Literal["front", "rear"]
META = (ProfileImageRow.id, ProfileImageRow.profile_id, ProfileImageRow.face, ProfileImageRow.variant,
        ProfileImageRow.content_type, ProfileImageRow.byte_size, ProfileImageRow.width_px,
        ProfileImageRow.height_px, ProfileImageRow.sha256, ProfileImageRow.version, ProfileImageRow.updated_at)


class ImageMeta(BaseModel):
    face: str
    content_type: str
    byte_size: int
    width_px: int
    height_px: int
    sha256: str
    version: int
    etag: str
    url: str
    thumb_url: str | None
    tex_url: str | None = None


def _profile(session: Session, type_id: int, profile_id: int) -> DeviceTypeProfileRow:
    p = session.get(DeviceTypeProfileRow, profile_id)
    if p is None or p.device_type_id != type_id:
        raise HTTPException(404, "Profile not found")
    return p


def _meta(session: Session, profile_id: int) -> list[ImageMeta]:
    rows = session.exec(select(*META).where(ProfileImageRow.profile_id == profile_id)).all()
    thumbs = {r.face: r.sha256 for r in rows if r.variant == "thumb"}
    texs = {r.face: r.sha256 for r in rows if r.variant == "tex"}
    return [ImageMeta(face=r.face, content_type=r.content_type, byte_size=r.byte_size, width_px=r.width_px,
                      height_px=r.height_px, sha256=r.sha256, version=r.version, etag=f'"{r.sha256}"',
                      url=image_url(profile_id, r.face, r.sha256),
                      thumb_url=image_url(profile_id, r.face, thumbs[r.face], "thumb") if r.face in thumbs else None,
                      tex_url=image_url(profile_id, r.face, texs[r.face], "tex") if r.face in texs else None)
            for r in rows if r.variant == "original"]


@router.get("/device-types/{type_id}/profiles/{profile_id}/images", response_model=list[ImageMeta])
def list_images(type_id: int, profile_id: int, session: Session = Depends(get_session)):
    _profile(session, type_id, profile_id)
    return _meta(session, profile_id)


def require_image_change_allowed(session: Session, profile: DeviceTypeProfileRow) -> None:
    """F-3 (approved): on a PUBLISHED profile only admins may upload, replace or delete images; technicians
    may still change images on drafts (or clone to a new draft version)."""
    if profile.status == "published" and getattr(session.info.get("user"), "role", None) != "admin":
        raise HTTPException(403, {"code": "image_change_requires_admin",
                                  "message": "Only an admin can change images on a published profile; "
                                             "create a new draft version instead"})


def save_image(session: Session, profile: DeviceTypeProfileRow, face: str, data: bytes, content_type: str | None,
               if_match: str | None = None, filename: str | None = None,
               processed: dict | None = None) -> tuple[ImageMeta, bool]:
    """Validate + store original and thumb (also used by the demo seed). Caller commits."""
    result = processed or service.process_bounded(data, content_type)
    existing = {r.variant: r for r in session.exec(select(ProfileImageRow).where(
        ProfileImageRow.profile_id == profile.id, ProfileImageRow.face == face)).all()}
    orig = existing.get("original")
    if if_match is not None and (orig is None or if_match.strip() not in (f'"{orig.sha256}"', orig.sha256, "*")):
        raise HTTPException(412, {"code": "image_changed", "message": "The image changed since you loaded it"})
    actor = getattr(session.info.get("user"), "email", None)
    before = {"sha256": orig.sha256, "version": orig.version, "byte_size": orig.byte_size} if orig else None
    for variant, info in result.items():
        row = existing.get(variant)
        if row is None:
            row = ProfileImageRow(profile_id=profile.id, face=face, variant=variant, **info)
            session.add(row)
        else:
            for k, v in info.items():
                setattr(row, k, v)
            row.version += 1
        row.uploaded_by = actor
        if variant == "original" and filename:
            row.original_filename = filename[:255]
    change_set = new_change_set(session, "api", note=f"profile {profile.id} {face} image")
    session.flush()
    o = result["original"]
    record_audit(session, None, "profile_image.replace" if orig else "profile_image.create", "profile", profile.id,
                 before=before, after={"profile_id": profile.id, "face": face, "profile_status": profile.status,
                                       "old_sha256": before["sha256"] if before else None, "new_sha256": o["sha256"],
                                       "sha256": o["sha256"], "byte_size": o["byte_size"],
                                       "width_px": o["width_px"], "height_px": o["height_px"],
                                       "change_set_id": change_set.id})
    return next(m for m in _meta(session, profile.id) if m.face == face), orig is None


@router.put("/device-types/{type_id}/profiles/{profile_id}/images/{face}", response_model=ImageMeta,
            dependencies=[Depends(TECH)],
            openapi_extra={"requestBody": {"required": True, "content": {
                t: {"schema": {"type": "string", "format": "binary"}} for t in service.FORMATS}}})
async def upload_image(type_id: int, profile_id: int, face: Face, request: Request, response: Response,
                       session: Session = Depends(get_session)):
    user = session.info.get("user")
    wait = upload_limiter.retry_after(f"user:{getattr(user, 'id', None)}",
                                      get_settings().image_uploads_per_minute, 60)
    if wait:
        raise HTTPException(429, "Too many image uploads; try again shortly", headers={"Retry-After": str(wait)})
    profile = _profile(session, type_id, profile_id)
    require_image_change_allowed(session, profile)
    data = await service.read_capped(request)
    from starlette.concurrency import run_in_threadpool
    processed = await run_in_threadpool(service.process_bounded, data, request.headers.get("content-type"))
    meta, created = save_image(session, profile, face, data, request.headers.get("content-type"),
                               request.headers.get("if-match"), processed=processed)
    session.commit()
    response.status_code = 201 if created else 200
    return meta


@router.delete("/device-types/{type_id}/profiles/{profile_id}/images/{face}", status_code=204,
               dependencies=[Depends(TECH)])
def delete_image(type_id: int, profile_id: int, face: Face, session: Session = Depends(get_session)):
    profile = _profile(session, type_id, profile_id)
    require_image_change_allowed(session, profile)
    if profile.status == "published":
        raise HTTPException(409, {"code": "profile_published",
                                  "message": f"A published profile needs its {face} image; upload a replacement"})
    rows = session.exec(select(ProfileImageRow).where(ProfileImageRow.profile_id == profile_id,
                                                      ProfileImageRow.face == face)).all()
    if not rows:
        raise HTTPException(404, "Image not found")
    orig = next((r for r in rows if r.variant == "original"), rows[0])
    change_set = new_change_set(session, "api", note=f"profile {profile_id} {face} image delete")
    session.flush()
    record_audit(session, None, "profile_image.delete", "profile", profile_id,
                 before={"face": face, "sha256": orig.sha256, "version": orig.version, "byte_size": orig.byte_size},
                 after={"profile_id": profile_id, "face": face, "profile_status": profile.status,
                        "old_sha256": orig.sha256, "new_sha256": None, "byte_size": orig.byte_size,
                        "change_set_id": change_set.id})
    for r in rows:
        session.delete(r)
    session.commit()
    return Response(status_code=204)


@router.get("/profile-images/{profile_id}/{face}", response_class=Response,
            responses={200: {"content": {t: {} for t in service.FORMATS}}, 304: {}, 404: {}})
def get_image(profile_id: int, face: Face, request: Request,
              variant: Literal["original", "thumb", "tex"] = Query("original", description="thumb = 512 px WebP, tex = 1024 px WebP"),
              v: str | None = Query(None, max_length=64, description="Content version; makes the URL immutable"),
              session: Session = Depends(get_session)):
    head = session.exec(select(ProfileImageRow.id, ProfileImageRow.sha256, ProfileImageRow.content_type,
                               ProfileImageRow.updated_at).where(
        ProfileImageRow.profile_id == profile_id, ProfileImageRow.face == face,
        ProfileImageRow.variant == variant)).first()
    if head is None:
        raise HTTPException(404, "Image not found")
    etag = f'"{head.sha256}"'
    # PROFILE_IMAGES §7: immutable only when ?v= is the current content version (sha256 prefix, >= 16 hex)
    current = bool(v) and len(v) >= 16 and head.sha256.startswith(v.lower())
    cache = "private, max-age=31536000, immutable" if current else "private, max-age=300, must-revalidate"
    headers = {"ETag": etag, "Cache-Control": cache, "X-Content-Type-Options": "nosniff",
               "Content-Security-Policy": "default-src 'none'; sandbox"}
    if head.updated_at is not None:
        headers["Last-Modified"] = head.updated_at.strftime("%a, %d %b %Y %H:%M:%S GMT")
    if etag in [t.strip() for t in request.headers.get("if-none-match", "").split(",")]:
        return Response(status_code=304, headers=headers)
    data = session.exec(select(ProfileImageRow.data).where(ProfileImageRow.id == head.id)).one()
    ext = service.FORMATS[head.content_type].lower().replace("jpeg", "jpg")
    headers["Content-Disposition"] = f'inline; filename="profile-{profile_id}-{face}.{ext}"'
    return Response(content=bytes(data), media_type=head.content_type, headers=headers)
