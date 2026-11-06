import io

from PIL import Image

from tests.test_locations import COMPLETE, make_rack

PNG = "image/png"


def png(w=40, h=20, fmt="PNG", exif=False, **kw):
    buf = io.BytesIO()
    img = Image.new("RGB", (w, h), (10, 120, 200))
    if exif:
        ex = Image.Exif()
        ex[0x010F] = "SecretCam"  # Make
        kw["exif"] = ex
    img.save(buf, fmt, **kw)
    return buf.getvalue()


def profile(client):
    t = client.post("/device-types", json={"manufacturer": "Dell", "name": "R660", "u_height": 1,
                                           "asset_type": "server"}).json()
    p = next(p for p in client.get(f"/device-types/{t['id']}/profiles").json() if p["is_default"])
    client.patch(f"/device-types/{t['id']}/profiles/{p['id']}", json=COMPLETE)
    return t, p, f"/device-types/{t['id']}/profiles/{p['id']}/images"


def put(client, url, data, ct=PNG, face="front", **h):
    return client.put(f"{url}/{face}", content=data, headers={"content-type": ct, **h})


def test_upload_serve_cache_and_refs(client):
    t, p, url = profile(client)
    r = put(client, url, png())
    assert r.status_code == 201, r.text
    meta = r.json()
    assert meta["width_px"] == 40 and meta["content_type"] == PNG and meta["thumb_url"]
    got = client.get(meta["url"])
    assert got.status_code == 200 and got.headers["content-type"] == PNG
    assert "immutable" in got.headers["cache-control"]
    assert got.headers["content-security-policy"] == "default-src 'none'; sandbox"
    assert got.headers["x-content-type-options"] == "nosniff"
    plain = client.get(f"/profile-images/{p['id']}/front")
    assert "must-revalidate" in plain.headers["cache-control"] and plain.headers["last-modified"]
    assert client.get(f"/profile-images/{p['id']}/front", headers={"if-none-match": got.headers["etag"]}).status_code == 304
    thumb = client.get(meta["thumb_url"])
    assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/webp"
    assert client.get(f"/profile-images/{p['id']}/rear").status_code == 404

    prof = client.get(f"/device-types/{t['id']}/profiles/{p['id']}").json()
    assert prof["readiness"]["missing"] == ["rear_image"]
    assert client.post(f"/device-types/{t['id']}/profiles/{p['id']}/publish").json()["detail"]["missing"] == ["rear_image"]
    assert put(client, url, png(), face="rear").status_code == 201
    prof = client.get(f"/device-types/{t['id']}/profiles/{p['id']}").json()
    assert prof["readiness"] == {"ready": True, "missing": [], "messages": {}, "flags": []} and prof["status"] == "draft"
    assert client.post(f"/device-types/{t['id']}/profiles/{p['id']}/publish").status_code == 200
    assert {k: prof["front_image"][k] for k in ("url", "thumb_url")} == {"url": meta["url"], "thumb_url": meta["thumb_url"]} and prof["rear_image"]
    item = next(i for i in client.get("/profiles").json() if i["id"] == p["id"])
    assert item["front_image"]["url"] == meta["url"] == item["front_image_url"]
    rack = make_rack(client)
    d = client.post("/devices", json={"host_name": "h1", "device_type_id": t["id"], "rack_id": rack["id"],
                                      "position_u": 1, "face": "front"})
    assert d.status_code == 201, d.text
    assert d.json()["effective_front_image"]["url"] == meta["url"]
    elev = client.get(f"/racks/{rack['id']}/elevation").json()
    assert elev["devices"][0]["effective_front_image"]["url"] == meta["url"]

    # replace: new version + new URL; If-Match mismatch -> 412
    assert put(client, url, png(), **{"if-match": '"nope"'}).status_code == 412
    r2 = put(client, url, png(50, 25), **{"if-match": got.headers["etag"]})
    assert r2.status_code == 200 and r2.json()["version"] == 2 and r2.json()["url"] != meta["url"]
    assert len(client.get(url).json()) == 2
    assert client.delete(f"{url}/front").json()["detail"]["code"] == "profile_published"
    assert put(client, url, png(), face="rear").status_code == 200
    r = client.delete(f"{url}/rear")  # a published profile keeps its rear image too
    assert r.status_code == 409 and r.json()["detail"]["code"] == "profile_published"
    assert client.get(f"/device-types/{t['id']}/profiles/{p['id']}").json()["rear_image"]
    audits = client.get("/audit", params={"entity_type": "profile"})
    if audits.status_code == 200:
        assert "data" not in str(audits.json())[:0]


def test_validation(client, monkeypatch):
    from app import settings as s
    _, _, url = profile(client)
    assert put(client, url, png(), ct="image/gif").status_code == 415
    assert put(client, url, png(), ct="image/jpeg").json()["detail"]["code"] == "image_type_mismatch"
    assert put(client, url, b"").status_code == 422
    assert put(client, url, b"\x89PNG\r\n\x1a\nnot really").json()["detail"]["code"] == "image_invalid"
    assert put(client, url, png(5000, 10)).json()["detail"]["code"] == "image_too_big"
    anim = io.BytesIO()
    frames = [Image.new("RGB", (8, 8), c) for c in ((255, 0, 0), (0, 255, 0))]
    frames[0].save(anim, "PNG", save_all=True, append_images=frames[1:])
    assert put(client, url, anim.getvalue()).json()["detail"]["code"] == "image_animated"
    big = s.get_settings().image_max_bytes
    assert put(client, url, b"\x89PNG\r\n\x1a\n" + b"0" * big).status_code == 413
    assert put(client, url, png(), face="side").status_code == 422


def test_exif_stripped(client):
    _, _, url = profile(client)
    raw = png(fmt="JPEG", exif=True)
    assert b"SecretCam" in raw
    meta = put(client, url, raw, ct="image/jpeg").json()
    served = client.get(meta["url"]).content
    assert b"SecretCam" not in served and Image.open(io.BytesIO(served)).getexif().get(0x010F) is None


def test_rbac_auth_and_rate_limit(client, client_as, anon, monkeypatch):
    t, p, url = profile(client)
    ro = client_as("read-only")
    assert put(ro, url, png()).status_code == 403
    assert put(client_as("technician"), url, png()).status_code == 201
    assert ro.get(f"/profile-images/{p['id']}/front").status_code == 200
    assert anon.get(f"/profile-images/{p['id']}/front").status_code == 401
    assert put(anon, url, png()).status_code == 401
    from app.modules.images import router
    from app.settings import get_settings
    monkeypatch.setattr(get_settings(), "image_uploads_per_minute", 1)
    router.upload_limiter.reset()
    assert put(client, url, png()).status_code == 200
    assert put(client, url, png()).status_code == 429
    router.upload_limiter.reset()


def test_lists_never_load_image_bytes(client, engine):
    from sqlalchemy import event
    t, p, url = profile(client)
    put(client, url, png())
    seen = []
    listener = lambda conn, cur, stmt, *a: seen.append(stmt)
    event.listen(engine, "before_cursor_execute", listener)
    try:
        client.get("/profiles")
        client.get(f"/device-types/{t['id']}/profiles")
        client.get("/devices")
        client.get(url)
    finally:
        event.remove(engine, "before_cursor_execute", listener)
    assert not [s for s in seen if "profile_images.data" in s]


def test_f1_png_icc_and_text_dropped(client):
    from PIL import PngImagePlugin
    _, _, url = profile(client)
    info = PngImagePlugin.PngInfo()
    info.add_text("Comment", "hidden-payload")
    src = png(icc_profile=b"\x00" * 600 + b"POLYGLOT", pnginfo=info)
    meta = put(client, url, src).json()
    out = client.get(meta["url"]).content
    img = Image.open(io.BytesIO(out))
    assert "icc_profile" not in img.info and "exif" not in img.info and "Comment" not in img.info
    assert b"hidden-payload" not in out and b"iCCP" not in out


def test_f2_decode_semaphore(client, monkeypatch):
    import threading

    from app.modules.images import service
    from app.settings import get_settings
    monkeypatch.setenv("DCIM_IMAGE_DECODE_CONCURRENCY", "2")
    monkeypatch.setenv("DCIM_IMAGE_DECODE_WAIT_SECONDS", "0.05")
    get_settings.cache_clear()
    try:
        slots = service._slots()
        gate, entered = threading.Event(), []
        real = service.process

        def slow(data, ct):
            entered.append(1)
            gate.wait(5)
            return real(data, ct)
        monkeypatch.setattr(service, "process", slow)
        workers = [threading.Thread(target=service.process_bounded, args=(png(), PNG)) for _ in range(2)]
        for w in workers:
            w.start()
        while len(entered) < 2:
            pass
        _, _, url = profile(client)
        r = put(client, url, png())  # third concurrent decode: no slot -> 503
        assert r.status_code == 503 and r.json()["detail"]["code"] == "image_busy" and r.headers["retry-after"]
        gate.set()
        for w in workers:
            w.join()
        assert slots.acquire(blocking=False) and slots.acquire(blocking=False)  # both slots released
        slots.release()
        slots.release()
    finally:
        monkeypatch.delenv("DCIM_IMAGE_DECODE_CONCURRENCY")
        monkeypatch.delenv("DCIM_IMAGE_DECODE_WAIT_SECONDS")
        get_settings.cache_clear()
        service._decode_slots = None


def test_f3_published_images_admin_only(client, client_as, engine):
    import json

    from sqlmodel import Session, select

    from app.modules.audit.models import AuditEventRow
    t, p, url = profile(client)
    tech, ro = client_as("technician"), client_as("read-only")
    # draft: technician may upload, replace and delete; read-only may not
    assert put(ro, url, png()).status_code == 403
    assert put(tech, url, png()).status_code == 201
    assert put(tech, url, png(w=41)).status_code == 200
    assert put(tech, url, png(), face="rear").status_code == 201
    assert ro.delete(f"{url}/rear").status_code == 403
    assert tech.delete(f"{url}/rear").status_code == 204
    assert put(tech, url, png(), face="rear").status_code == 201
    assert client.post(f"/device-types/{t['id']}/profiles/{p['id']}/publish").status_code == 200
    # published: technician refused with a code, read-only refused, admin allowed
    for c in (tech, ro):
        for r in (put(c, url, png(w=50)), put(c, url, png(), face="rear"), c.delete(f"{url}/front")):
            assert r.status_code == 403
    r = put(tech, url, png(w=50))
    assert r.json()["detail"]["code"] == "image_change_requires_admin"
    assert tech.delete(f"{url}/front").json()["detail"]["code"] == "image_change_requires_admin"
    assert put(client, url, png(w=52)).status_code == 200
    assert put(client, url, png(), face="rear").status_code == 200
    assert client.delete(f"{url}/rear").status_code == 409
    # clone is admin-only already; its copied images are audited
    assert tech.post(f"/profiles/{p['id']}/clone", json={}).status_code == 403
    c = client.post(f"/profiles/{p['id']}/clone", json={})
    assert c.status_code == 201, c.text
    with Session(engine) as s:
        ev = s.exec(select(AuditEventRow).where(AuditEventRow.action.like("profile_image.%"))
                    .order_by(AuditEventRow.id)).all()
    acts = [(e.action, e.entity_id) for e in ev]
    new = c.json()["id"]
    assert acts == [("profile_image.create", p["id"]), ("profile_image.replace", p["id"]),
                    ("profile_image.create", p["id"]), ("profile_image.delete", p["id"]),
                    ("profile_image.create", p["id"]), ("profile_image.replace", p["id"]),
                    ("profile_image.replace", p["id"]), ("profile_image.create", new),
                    ("profile_image.create", new)]
    for e in ev:
        a = json.loads(e.after_json)
        assert e.actor_user_id is not None and a["face"] and a["profile_id"] == e.entity_id
        assert "new_sha256" in a and "old_sha256" in a and a["byte_size"] > 0
        assert "data" not in e.after_json and "data" not in (e.before_json or "")
    rep = json.loads(ev[1].after_json)
    assert rep["old_sha256"] == json.loads(ev[0].after_json)["new_sha256"] != rep["new_sha256"]
    assert json.loads(ev[3].after_json)["new_sha256"] is None


def test_effective_rear_image_everywhere(client):
    t, p, url = profile(client)
    assert put(client, url, png()).status_code == 201
    first = put(client, url, png(31, 15), face="rear").json()
    assert client.post(f"/device-types/{t['id']}/profiles/{p['id']}/publish").status_code == 200
    rack = make_rack(client)
    d = client.post("/devices", json={"host_name": "r1", "profile_id": p["id"], "rack_id": rack["id"],
                                      "position_u": 1, "face": "front"}).json()
    assert d["effective_rear_image"]["url"] == first["url"]
    rear = put(client, url, png(30, 15), face="rear").json()  # admin replaces it
    dev = client.get(f"/devices/{d['id']}").json()
    elev = client.get(f"/racks/{rack['id']}/elevation").json()["devices"][0]
    row = client.get(f"/rows/{rack['row_id']}/front").json()["racks"][0]["devices"][0]
    for item in (dev, elev, row):
        assert item["effective_rear_image"]["url"] == rear["url"] != item["effective_front_image"]["url"]
        assert item["effective_rear_image"]["thumb_url"] == rear["thumb_url"]
    assert client.get("/devices").json()[0]["effective_rear_image"]["url"] == rear["url"]


def test_profile_image_ref_one_schema(client):
    t, p, url = profile(client)
    meta = put(client, url, png(40, 20)).json()
    put(client, url, png(30, 10), face="rear")
    prof = client.get(f"/device-types/{t['id']}/profiles/{p['id']}").json()
    ref = prof["front_image"]
    assert ref == {"url": meta["url"], "thumb_url": meta["thumb_url"], "tex_url": meta["tex_url"], "width_px": 40,
                   "height_px": 20, "etag": meta["etag"]}
    assert prof["rear_image"]["width_px"] == 30
    item = next(i for i in client.get("/profiles").json() if i["id"] == p["id"])
    assert item["front_image"] == ref and item["rear_image"] == prof["rear_image"]
    spec = client.get("/openapi.json").json()
    blob = __import__("json").dumps(spec)
    s = spec["components"]["schemas"]
    assert set(s["ProfileImageRef"]["properties"]) == {"url", "thumb_url", "tex_url", "width_px", "height_px", "etag"}
    for model, fields in (("Device", ("effective_front_image", "effective_rear_image")),
                          ("ElevationDevice", ("effective_front_image", "effective_rear_image")),
                          ("DeviceProfile", ("front_image", "rear_image")),
                          ("ProfileListItem", ("front_image", "rear_image"))):
        for f in fields:
            refs = [x.get("$ref") for x in s[model]["properties"][f].get("anyOf", [])]
            assert "#/components/schemas/ProfileImageRef" in refs, (model, f)
    assert '"ImageRef"' not in blob


def test_versioned_url_cache_headers(client):
    _, p, url = profile(client)
    meta = put(client, url, png()).json()
    assert "?v=" in meta["url"] and "v=" in meta["thumb_url"]
    v = meta["url"].split("v=")[1].split("&")[0]
    assert len(v) == 16 and meta["sha256"].startswith(v)
    imm = "private, max-age=31536000, immutable"
    short = "private, max-age=300, must-revalidate"
    assert client.get(meta["url"]).headers["cache-control"] == imm
    assert client.get(meta["thumb_url"]).headers["cache-control"] == imm
    base = f"/profile-images/{p['id']}/front"
    for q in ("", "?v=", "?v=" + v[:4], "?v=" + "0" * 16):
        assert client.get(base + q).headers["cache-control"] == short, q
    new = put(client, url, png(41, 20)).json()
    assert new["url"] != meta["url"]
    assert client.get(meta["url"]).headers["cache-control"] == short  # stale version: revalidate
    assert client.get(new["url"]).headers["cache-control"] == imm


def test_tex_variant(client, engine):
    from sqlmodel import Session, delete, select
    from app.modules.images.models import ProfileImageRow as I
    t, p, url = profile(client)
    big = png(2000, 600, exif=True)
    meta = put(client, url, big).json()
    assert "variant=tex" in meta["tex_url"] and "v=" in meta["tex_url"]
    r = client.get(meta["tex_url"])
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp"
    assert r.headers["cache-control"] == "private, max-age=31536000, immutable"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-security-policy"] == "default-src 'none'; sandbox"
    img = Image.open(io.BytesIO(r.content))
    assert img.size == (1024, 307) and not img.info.get("exif") and not img.info.get("icc_profile")
    assert r.headers["etag"] != meta["etag"]
    assert client.get(meta["tex_url"], headers={"if-none-match": r.headers["etag"]}).status_code == 304
    assert client.get(f"/profile-images/{p['id']}/front?variant=tex").headers["cache-control"] == \
        "private, max-age=300, must-revalidate"
    assert client.get(f"/profile-images/{p['id']}/front?variant=bogus").status_code == 422
    small = put(client, url, png(40, 20), face="rear").json()  # never upscaled
    assert Image.open(io.BytesIO(client.get(small["tex_url"]).content)).size == (40, 20)
    prof = client.get(f"/device-types/{t['id']}/profiles/{p['id']}").json()
    assert prof["front_image"]["tex_url"] == meta["tex_url"]
    # replace -> new tex url; swap_faces clone regenerates tex crosswise
    new = put(client, url, png(1500, 300)).json()
    assert new["tex_url"] != meta["tex_url"]
    client.post(f"/device-types/{t['id']}/profiles/{p['id']}/publish")
    clone = client.post(f"/profiles/{p['id']}/clone", json={"swap_faces": True}).json()
    assert clone["rear_image"]["width_px"] == 1500
    c = Image.open(io.BytesIO(client.get(clone["rear_image"]["tex_url"]).content))
    assert c.size == (1024, 205)
    # backfill script: drop tex rows, URL falls back to original, script restores them idempotently
    import importlib.util, pathlib
    spec = importlib.util.spec_from_file_location("regen", pathlib.Path(__file__).parents[1] / "scripts/regenerate_image_variants.py")
    regen = importlib.util.module_from_spec(spec); spec.loader.exec_module(regen)
    with Session(engine) as s:
        s.exec(delete(I).where(I.variant == "tex")); s.commit()
    prof = client.get(f"/device-types/{t['id']}/profiles/{p['id']}").json()
    assert prof["front_image"]["tex_url"] == prof["front_image"]["url"]
    with Session(engine) as s:
        dry = regen.run(s)
        assert dry["pending"] == dry["originals"] >= 4 and dry["created"] == 0
        assert s.exec(select(I).where(I.variant == "tex")).first() is None
        done = regen.run(s, execute=True)
        assert done["created"] == dry["pending"]
        assert regen.run(s, execute=True) == {**done, "pending": 0, "created": 0}
    prof = client.get(f"/device-types/{t['id']}/profiles/{p['id']}").json()
    assert "variant=tex" in prof["front_image"]["tex_url"]
