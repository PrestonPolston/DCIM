"""Image URLs for JSON responses (never bytes). Versioned by content hash so a replaced image gets a new URL."""
from pydantic import BaseModel
from sqlmodel import Session, select

from app.modules.images.models import ProfileImageRow


class ProfileImageRef(BaseModel):
    """One shape for every image reference in JSON (front_image, rear_image, effective_*_image)."""
    url: str  # content-versioned (?v=<sha256 prefix>): cache it as immutable
    thumb_url: str
    tex_url: str  # 1024 px WebP for 3D textures (?variant=tex); falls back to the original URL until backfilled
    width_px: int
    height_px: int
    etag: str  # '"<sha256>"' of the original, as sent by GET /profile-images


def image_url(profile_id: int, face: str, sha: str, variant: str = "original") -> str:
    q = f"v={sha[:16]}"
    return f"/profile-images/{profile_id}/{face}?{q}" + (f"&variant={variant}" if variant in ("thumb", "tex") else "")


def image_refs(session: Session, profile_ids) -> dict[tuple[int, str], dict]:
    """{(profile_id, face): ProfileImageRef fields} for originals that exist; selects no blob columns."""
    ids = {p for p in profile_ids if p is not None}
    if not ids:
        return {}
    rows = session.exec(select(ProfileImageRow.profile_id, ProfileImageRow.face, ProfileImageRow.variant,
                               ProfileImageRow.sha256, ProfileImageRow.width_px, ProfileImageRow.height_px)
                        .where(ProfileImageRow.profile_id.in_(ids))).all()
    by = {(p, f, v): (sha, w, h) for p, f, v, sha, w, h in rows}
    out = {}
    for (p, f, v), (sha, w, h) in by.items():
        if v == "original":
            thumb = by.get((p, f, "thumb"), (sha,))[0]
            tex = by.get((p, f, "tex"))
            out[(p, f)] = {"url": image_url(p, f, sha), "thumb_url": image_url(p, f, thumb, "thumb"),
                           "tex_url": image_url(p, f, tex[0], "tex") if tex else image_url(p, f, sha),
                           "width_px": w, "height_px": h, "etag": f'"{sha}"'}
    return out
