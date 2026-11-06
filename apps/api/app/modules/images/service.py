"""Upload pipeline (item 25), in order: streaming size cap -> magic bytes -> header dims (bomb guard)
-> bounded single-frame decode -> re-encode without metadata -> sha256/dims -> 512 px WebP thumbnail."""
import hashlib
import io
import threading
import warnings

from fastapi import HTTPException, Request
from PIL import Image, ImageOps, UnidentifiedImageError

from app.settings import get_settings

MAGIC = {"image/png": (b"\x89PNG\r\n\x1a\n",), "image/jpeg": (b"\xff\xd8\xff",)}
FORMATS = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}
THUMB_PX = 512
TEX_PX = 1024  # D51: 3D texture variant (WebP, longest side <= 1024)
DERIVED = {"thumb": THUMB_PX, "tex": TEX_PX}


def _err(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


async def read_capped(request: Request) -> bytes:
    limit = get_settings().image_max_bytes
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise _err(413, "image_too_large", f"Image is larger than {limit} bytes")
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > limit:
            raise _err(413, "image_too_large", f"Image is larger than {limit} bytes")
    if not buf:
        raise _err(422, "image_empty", "Send the image bytes as the request body")
    return bytes(buf)


def sniff(data: bytes) -> str | None:
    for ct, sigs in MAGIC.items():
        if any(data.startswith(s) for s in sigs):
            return ct
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _encode(img: Image.Image, fmt: str) -> bytes:
    out = io.BytesIO()
    if fmt == "JPEG":
        img.convert("RGB").save(out, "JPEG", quality=90, optimize=True)  # no exif/icc/comments passed
    elif fmt == "PNG":
        img.save(out, "PNG", optimize=True, icc_profile=None)  # F-1: no ICC; no pnginfo -> text chunks dropped
    else:
        img.save(out, "WEBP", quality=90, method=4)
    return out.getvalue()


_decode_slots: threading.BoundedSemaphore | None = None
_slots_size = 0
_slots_lock = threading.Lock()


def _slots() -> threading.BoundedSemaphore:
    global _decode_slots, _slots_size
    n = max(1, get_settings().image_decode_concurrency)
    with _slots_lock:
        if _decode_slots is None or _slots_size != n:
            _decode_slots, _slots_size = threading.BoundedSemaphore(n), n
        return _decode_slots


def process_bounded(data: bytes, declared_type: str | None) -> dict:
    """F-2: at most DCIM_IMAGE_DECODE_CONCURRENCY decodes at once per process; waiters give up with 503."""
    slots = _slots()
    if not slots.acquire(timeout=get_settings().image_decode_wait_seconds):
        raise HTTPException(503, {"code": "image_busy", "message": "Too many images are being processed; retry"},
                            headers={"Retry-After": "2"})
    try:
        return process(data, declared_type)
    finally:
        slots.release()


def process(data: bytes, declared_type: str | None) -> dict:
    s = get_settings()
    ct = sniff(data)
    if ct is None:
        raise _err(415, "image_type_not_allowed", "Only PNG, JPEG and WebP images are accepted")
    declared = (declared_type or "").split(";")[0].strip().lower()
    if declared and declared != "application/octet-stream" and declared != ct:
        raise _err(415, "image_type_mismatch", f"Content-Type {declared} does not match the file ({ct})")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            img = Image.open(io.BytesIO(data))  # lazy: reads the header only
            w, h = img.size
            if w > s.image_max_px or h > s.image_max_px or w * h > s.image_max_pixels:
                raise _err(422, "image_too_big", f"Image is {w}x{h}; the limit is {s.image_max_px} px per side "
                                                 f"and {s.image_max_pixels} pixels")
            if getattr(img, "n_frames", 1) > 1:
                raise _err(422, "image_animated", "Animated or multi-frame images are not accepted")
            img.load()
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError,
            Image.DecompressionBombWarning):
        raise _err(422, "image_invalid", "The image could not be decoded") from None
    img = ImageOps.exif_transpose(img)
    img.info = {}  # F-1: nothing from the source (icc, exif, text, comments) reaches an encoder
    if img.mode not in ("RGB", "RGBA", "L", "LA"):
        img = img.convert("RGBA" if "A" in img.getbands() or img.mode == "P" else "RGB")
    clean = _encode(img, FORMATS[ct])
    w, h = img.size
    out = {"original": {"content_type": ct, "data": clean, "byte_size": len(clean), "width_px": w, "height_px": h,
                        "sha256": hashlib.sha256(clean).hexdigest()}}
    out.update(derive(img))
    return out


def derive(img: Image.Image) -> dict:
    """thumb (512) + tex (1024) WebP variants from a decoded, metadata-free image; never upscaled."""
    out = {}
    for variant, px in DERIVED.items():
        small = img.copy()
        small.info = {}
        small.thumbnail((px, px))
        b = _encode(small, "WEBP")
        out[variant] = {"content_type": "image/webp", "data": b, "byte_size": len(b),
                        "width_px": small.size[0], "height_px": small.size[1],
                        "sha256": hashlib.sha256(b).hexdigest()}
    return out
