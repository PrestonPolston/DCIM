"""Cabinet profiles (p1_28/p1_29, MIGRATION_SPEC_CABINET_PROFILES.md): CRUD, lifecycle, names, units, roles,
images (generated in code; no image files in the repo)."""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.modules.audit.models import AuditEventRow
from app.modules.cabinet_profiles.models import CabinetProfileImageRow
from tests.test_profile_images import png

COMPLETE = {"u_height": 42, "width_mm": 600, "height_mm": 2000, "depth_mm": 1200, "rack_unit_width": "19in"}


def mk(client, **kw):
    body = {"manufacturer": "Acme", "model": "R1", **kw}
    r = client.post("/cabinet-profiles", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def published(client, **kw):
    p = mk(client, **COMPLETE, **kw)
    r = client.post(f"/cabinet-profiles/{p['id']}/publish")
    assert r.status_code == 200, r.text
    return r.json()


def code(r):
    d = r.json()["detail"]
    return d["code"] if isinstance(d, dict) else d[0]["type"]


def test_crud_and_draft_incomplete(client):
    p = mk(client)
    assert p["status"] == "draft" and p["name"] == "Standard" and p["version"] == 1
    assert p["readiness"] == {"ready": False, "missing": ["u_height", "width_mm", "height_mm", "depth_mm",
                                                          "rack_unit_width"]}
    assert p["created_by"] == "admin1@example.com" and p["front_image"] is None
    r = client.patch(f"/cabinet-profiles/{p['id']}", json={"notes": "hot aisle", "front_door": "perforated",
                                                          "rail_type": "square_hole", "weight_capacity_kg": 1500})
    assert r.status_code == 200 and r.json()["front_door"] == "perforated" and r.json()["weight_capacity_kg"] == 1500
    assert client.get(f"/cabinet-profiles/{p['id']}").json()["notes"] == "hot aisle"
    lst = client.get("/cabinet-profiles?q=acm")
    assert lst.headers["X-Total-Count"] == "1"
    assert client.get("/cabinet-profiles?status=published").json() == []
    assert client.delete(f"/cabinet-profiles/{p['id']}").status_code == 204
    assert client.get(f"/cabinet-profiles/{p['id']}").status_code == 404


def test_publish_rules_and_images_optional(client):
    p = mk(client, u_height=48)
    r = client.post(f"/cabinet-profiles/{p['id']}/publish")
    assert r.status_code == 422 and code(r) == "cabinet_profile_incomplete"
    assert r.json()["detail"]["missing"] == ["width_mm", "height_mm", "depth_mm", "rack_unit_width"]
    for field in ("width_mm", "height_mm", "depth_mm", "rack_unit_width"):
        body = {**COMPLETE, "u_height": 48}
        body.pop(field)
        q = mk(client, model=f"M-{field}", **body)
        r = client.post(f"/cabinet-profiles/{q['id']}/publish")
        assert r.status_code == 422 and r.json()["detail"]["missing"] == [field]
    ok = published(client, model="R2")  # no images at all
    assert ok["status"] == "published" and ok["published_at"] and ok["published_by"] == "admin1@example.com"
    assert client.post(f"/cabinet-profiles/{ok['id']}/publish").status_code == 200  # idempotent


def test_published_editable_but_stays_complete(client):
    p = published(client)
    r = client.patch(f"/cabinet-profiles/{p['id']}", json={"width_mm": 800})
    assert r.status_code == 200 and r.json()["width_mm"] == 800
    r = client.patch(f"/cabinet-profiles/{p['id']}", json={"depth_mm": None})
    assert r.status_code == 422 and code(r) == "cabinet_profile_incomplete" and r.json()["detail"]["missing"] == ["depth_mm"]


def test_lifecycle_retire_unretire_and_forbidden(client):
    d = mk(client, **COMPLETE)
    r = client.post(f"/cabinet-profiles/{d['id']}/retire")
    assert r.status_code == 422 and code(r) == "invalid_status_transition"
    r = client.post(f"/cabinet-profiles/{d['id']}/unretire")
    assert r.status_code == 422 and code(r) == "invalid_status_transition"
    p = published(client, model="R2")
    assert client.post(f"/cabinet-profiles/{p['id']}/unretire").status_code == 422
    r = client.post(f"/cabinet-profiles/{p['id']}/retire")
    assert r.status_code == 200 and r.json()["status"] == "retired" and r.json()["retired_by"]
    r = client.patch(f"/cabinet-profiles/{p['id']}", json={"notes": "x"})
    assert r.status_code == 409 and code(r) == "cabinet_profile_retired"
    assert client.post(f"/cabinet-profiles/{p['id']}/publish").status_code == 422  # retired -> publish: unretire
    r = client.post(f"/cabinet-profiles/{p['id']}/unretire")
    assert r.status_code == 200 and r.json()["status"] == "published" and r.json()["retired_at"] is None


def test_name_unique_ignoring_case(client):
    a = mk(client, name="Standard")
    r = client.post("/cabinet-profiles", json={"manufacturer": "ACME", "model": "r1", "name": "standard"})
    assert r.status_code == 409 and code(r) == "cabinet_profile_name_taken"
    assert r.json()["detail"]["existing_id"] == a["id"]
    b = mk(client, name="Deep")
    r = client.patch(f"/cabinet-profiles/{b['id']}", json={"name": "STANDARD"})
    assert r.status_code == 409 and code(r) == "cabinet_profile_name_taken"


def test_db_unique_ignoring_case(engine):
    with Session(engine) as s:
        s.exec(text("INSERT INTO cabinet_profiles(manufacturer, model, name) VALUES ('Acme','R1','Standard')"))
        s.commit()
        with pytest.raises(IntegrityError):
            s.exec(text("INSERT INTO cabinet_profiles(manufacturer, model, name) VALUES ('acme','r1','STANDARD')"))
            s.commit()


def test_version_conflict(client):
    p = mk(client)
    stale = p["updated_at"]
    assert client.patch(f"/cabinet-profiles/{p['id']}", json={"notes": "a", "expected_updated_at": stale}).status_code == 200
    r = client.patch(f"/cabinet-profiles/{p['id']}", json={"notes": "b", "expected_updated_at": stale})
    assert r.status_code == 409 and code(r) == "version_conflict"
    d = r.json()["detail"]
    assert d["updated_by"] == "admin1@example.com" and d["current_updated_at"].endswith("+00:00")


def test_units_in_and_mm(client):
    p = mk(client, unit="in", width_mm=23.62, height_mm=78.74, depth_mm=47.25, rail_depth_max_mm=29.5)
    assert (p["width_mm"], p["height_mm"], p["depth_mm"], p["rail_depth_max_mm"]) == (600, 2000, 1200, 749)
    r = client.patch(f"/cabinet-profiles/{p['id']}", json={"unit": "mm", "width_mm": 800})
    assert r.json()["width_mm"] == 800 and "unit" not in r.json()
    r = client.patch(f"/cabinet-profiles/{p['id']}", json={"unit": "in", "width_mm": 0.01})  # rounds to 0 mm
    assert r.status_code == 422
    r = client.post("/cabinet-profiles", json={"manufacturer": "A", "model": "B", "unit": "cm", "width_mm": 1})
    assert r.status_code == 422 and code(r) == "invalid_unit"
    r = client.post("/cabinet-profiles", json={"manufacturer": "A", "model": "B", "rack_unit_width": "21in"})
    assert r.status_code == 422  # 19in / 23in only


def test_dimension_rules(client):
    r = client.post("/cabinet-profiles", json={"manufacturer": "A", "model": "B", "width_mm": 0})
    assert r.status_code == 422
    r = client.post("/cabinet-profiles", json={"manufacturer": "A", "model": "B", "depth_mm": 1000,
                                               "rail_depth_min_mm": 900, "rail_depth_max_mm": 800})
    assert r.status_code == 422 and code(r) == "invalid_dimension"
    r = client.post("/cabinet-profiles", json={"manufacturer": "A", "model": "B", "width_mm": 9999,
                                               "weight_capacity_kg": 99999})
    assert r.status_code == 201  # API: only > 0 (Preston)
    r = client.post("/cabinet-profiles", json={"manufacturer": "A", "model": "C", "width_mm": 20000,
                                               "weight_capacity_kg": 250000})
    assert r.status_code == 201  # no upper caps (Preston): API or DB
    r = client.post("/cabinet-profiles", json={"manufacturer": "A", "model": "B2", "width_mm": 600,
                                               "usable_width_mm": 700})
    assert r.status_code == 422 and r.json()["detail"]["fields"] == ["usable_width_mm"]


@pytest.mark.parametrize("sql", [
    "INSERT INTO cabinet_profiles(manufacturer, model, status) VALUES ('A','B','bogus')",
    "INSERT INTO cabinet_profiles(manufacturer, model) VALUES ('  ','B')",
    "INSERT INTO cabinet_profiles(manufacturer, model, u_height) VALUES ('A','B',101)",
    "INSERT INTO cabinet_profiles(manufacturer, model, width_mm) VALUES ('A','B',0)",
    "INSERT INTO cabinet_profiles(manufacturer, model, rack_unit_width) VALUES ('A','B','21in')",
    "INSERT INTO cabinet_profiles(manufacturer, model, rail_type) VALUES ('A','B','cage')",
    "INSERT INTO cabinet_profiles(manufacturer, model, front_door) VALUES ('A','B','glass')",
    "INSERT INTO cabinet_profiles(manufacturer, model, depth_mm, rail_depth_max_mm) VALUES ('A','B',100,200)",
    "INSERT INTO cabinet_profiles(manufacturer, model, width_mm, usable_width_mm) VALUES ('A','B',100,200)",
    "INSERT INTO cabinet_profiles(manufacturer, model, weight_capacity_kg) VALUES ('A','B',0)",
    "INSERT INTO cabinet_profiles(manufacturer, model, color_hex) VALUES ('A','B','red')",
    "INSERT INTO cabinet_profiles(manufacturer, model, status, published_at) VALUES ('A','B','published',CURRENT_TIMESTAMP)",
    "INSERT INTO cabinet_profiles(manufacturer, model, status, u_height, width_mm, height_mm, depth_mm, rack_unit_width)"
    " VALUES ('A','B','published',42,600,2000,1200,'19in')",  # published_at missing
    "INSERT INTO cabinet_profiles(manufacturer, model, retired_at) VALUES ('A','B',CURRENT_TIMESTAMP)",
])
def test_check_backstops(engine, sql):
    with Session(engine) as s:
        with pytest.raises(IntegrityError):
            s.exec(text(sql))
            s.commit()


def test_delete_rules(client):
    p = published(client)
    c = client.post(f"/cabinet-profiles/{p['id']}/clone").json()
    r = client.delete(f"/cabinet-profiles/{p['id']}")
    assert r.status_code == 409 and code(r) == "cabinet_profile_in_use" and r.json()["detail"]["reason"] == "superseded"
    assert client.delete(f"/cabinet-profiles/{c['id']}").status_code == 204
    assert client.delete(f"/cabinet-profiles/{p['id']}").status_code == 204  # published, unreferenced
    r2 = published(client, model="R9")
    client.post(f"/cabinet-profiles/{r2['id']}/retire")
    assert client.delete(f"/cabinet-profiles/{r2['id']}").status_code == 204  # retired, unreferenced
    assert client.delete("/cabinet-profiles/9999").status_code == 404


def _put(client, pid, data, face="front", ct="image/png"):
    return client.put(f"/cabinet-profiles/{pid}/images/{face}", content=data, headers={"content-type": ct})


def test_images_upload_serve_delete(client):
    p = mk(client)
    r = _put(client, p["id"], png(3000, 1500))
    assert r.status_code == 201, r.text
    meta = r.json()
    assert meta["url"].startswith(f"/cabinet-profile-images/{p['id']}/front?v=") and meta["tex_url"]
    got = client.get(meta["url"])
    assert got.status_code == 200 and got.headers["content-type"] == "image/png"
    assert "immutable" in got.headers["cache-control"]
    assert client.get(meta["url"], headers={"if-none-match": got.headers["etag"]}).status_code == 304
    tex = client.get(meta["tex_url"])
    assert tex.headers["content-type"] == "image/webp"
    assert client.get(f"/cabinet-profiles/{p['id']}").json()["front_image"]["width_px"] == 3000
    assert _put(client, p["id"], png(10, 10)).status_code == 200  # replace
    assert client.delete(f"/cabinet-profiles/{p['id']}/images/front").status_code == 204
    assert client.delete(f"/cabinet-profiles/{p['id']}/images/front").status_code == 404
    assert client.get(meta["url"]).status_code == 404


def test_image_validation(client):
    p = mk(client)
    assert _put(client, p["id"], b"not an image").status_code == 415
    assert _put(client, p["id"], png(), ct="image/jpeg").status_code == 415
    r = _put(client, p["id"], png(4097, 10))
    assert r.status_code == 422 and code(r) == "image_too_big"
    big = b"\x89PNG\r\n\x1a\n" + b"0" * (2 * 1024 * 1024 + 1)
    assert _put(client, p["id"], big).status_code == 413
    assert client.put(f"/cabinet-profiles/{p['id']}/images/side", content=png()).status_code == 422


def test_clone_copies_fields_and_images(client, engine):
    p = published(client, notes="n", rail_type="round_hole")
    _put(client, p["id"], png(40, 20))
    _put(client, p["id"], png(30, 20), face="rear")
    r = client.post(f"/cabinet-profiles/{p['id']}/clone")
    assert r.status_code == 201, r.text
    c = r.json()
    assert (c["status"], c["version"], c["supersedes_cabinet_profile_id"], c["name"]) == ("draft", 2, p["id"], "Standard (copy)")
    assert c["notes"] == "n" and c["rail_type"] == "round_hole" and c["published_at"] is None
    with Session(engine) as s:
        src = s.exec(select(CabinetProfileImageRow).where(CabinetProfileImageRow.cabinet_profile_id == p["id"])).all()
        dst = s.exec(select(CabinetProfileImageRow).where(CabinetProfileImageRow.cabinet_profile_id == c["id"])).all()
        assert len(src) == len(dst) == 6
        assert {(i.face, i.variant, i.sha256) for i in src} == {(i.face, i.variant, i.sha256) for i in dst}
        assert not {i.id for i in src} & {i.id for i in dst}
    again = client.post(f"/cabinet-profiles/{p['id']}/clone")  # "(copy)" taken -> next free name
    assert again.status_code == 201 and again.json()["name"] == "Standard (copy 2)"
    assert client.post(f"/cabinet-profiles/{p['id']}/clone").json()["name"] == "Standard (copy 3)"
    r = client.post(f"/cabinet-profiles/{p['id']}/clone", json={"name": "standard (COPY)"})  # explicit, taken
    assert r.status_code == 409 and code(r) == "cabinet_profile_name_taken"
    assert client.post(f"/cabinet-profiles/{p['id']}/clone", json={"name": "V3"}).status_code == 201
    client.delete(f"/cabinet-profiles/{c['id']}")
    assert client.get(client.get(f"/cabinet-profiles/{p['id']}").json()["front_image"]["url"]).status_code == 200


def test_audit_events(client, engine):
    p = mk(client, **COMPLETE)
    client.patch(f"/cabinet-profiles/{p['id']}", json={"notes": "x"})
    client.post(f"/cabinet-profiles/{p['id']}/publish")
    _put(client, p["id"], png())
    client.post(f"/cabinet-profiles/{p['id']}/retire")
    client.post(f"/cabinet-profiles/{p['id']}/unretire")
    c = client.post(f"/cabinet-profiles/{p['id']}/clone").json()
    client.delete(f"/cabinet-profiles/{c['id']}")
    with Session(engine) as s:
        actions = [a for a in s.exec(select(AuditEventRow.action).where(
            AuditEventRow.entity_type == "cabinet_profile")).all()]
        snap = s.exec(select(AuditEventRow).where(AuditEventRow.action == "cabinet_profile.delete")).one()
    for a in ("create", "update", "publish", "image.put", "retire", "unretire", "clone", "delete"):
        assert f"cabinet_profile.{a}" in actions, (a, actions)
    assert '"model": "R1"' in snap.before_json and '"version": 2' in snap.before_json


@pytest.mark.parametrize("role", ["technician", "read-only"])
def test_writes_admin_only_reads_for_all(client, client_as, role):
    p = published(client)
    other = client_as(role)
    assert other.get("/cabinet-profiles").status_code == 200
    assert other.get(f"/cabinet-profiles/{p['id']}").status_code == 200
    calls = [("POST", "/cabinet-profiles", {"manufacturer": "X", "model": "Y"}),
             ("PATCH", f"/cabinet-profiles/{p['id']}", {"notes": "x"}),
             ("DELETE", f"/cabinet-profiles/{p['id']}", None),
             ("POST", f"/cabinet-profiles/{p['id']}/publish", None),
             ("POST", f"/cabinet-profiles/{p['id']}/retire", None),
             ("POST", f"/cabinet-profiles/{p['id']}/unretire", None),
             ("POST", f"/cabinet-profiles/{p['id']}/clone", None),
             ("DELETE", f"/cabinet-profiles/{p['id']}/images/front", None)]
    for method, url, body in calls:
        r = other.request(method, url, json=body)
        assert r.status_code == 403, (method, url, r.status_code)
    r = other.put(f"/cabinet-profiles/{p['id']}/images/front", content=png(), headers={"content-type": "image/png"})
    assert r.status_code == 403
    _put(client, p["id"], png())
    assert other.get(client.get(f"/cabinet-profiles/{p['id']}").json()["front_image"]["url"]).status_code == 200


def test_empty_db_no_seed(client):
    assert client.get("/cabinet-profiles").json() == []


def test_rack_count_and_history(client, client_as):
    p = mk(client, **COMPLETE)
    assert p["rack_count"] == 0
    client.patch(f"/cabinet-profiles/{p['id']}", json={"notes": "x"})
    client.post(f"/cabinet-profiles/{p['id']}/publish")
    r = client.get(f"/cabinet-profiles/{p['id']}/history")
    assert r.status_code == 200 and r.headers["X-Total-Count"] == "4"
    ev = r.json()  # publish = explicit event + the listener's field diff
    assert [e["action"] for e in ev] == ["cabinet_profile.publish", "cabinet_profile.update", "cabinet_profile.update",
                                         "cabinet_profile.create"]
    assert ev[1]["after"]["status"] == "published" and ev[2]["after"] == {"notes": "x"}
    assert ev[0]["actor_email"] == "admin1@example.com"
    assert client_as("technician").get(f"/cabinet-profiles/{p['id']}/history").status_code == 403


def _has_offset(v):
    return v is None or v.endswith("Z") or v.endswith("+00:00")


def test_timestamps_utc_and_updated_by(client, client_as):
    p = published(client)
    other = client_as("admin", email="second@example.com")
    other.post(f"/cabinet-profiles/{p['id']}/retire")
    got = client.get(f"/cabinet-profiles/{p['id']}").json()
    for k in ("created_at", "updated_at", "published_at", "retired_at"):
        assert got[k] and _has_offset(got[k]), (k, got[k])
    assert got["updated_by"] == "second@example.com" and got["created_by"] == "admin1@example.com"
    un = client.post(f"/cabinet-profiles/{p['id']}/unretire").json()
    assert un["retired_at"] is None and un["retired_by"] is None and un["updated_by"] == "admin1@example.com"
    for e in client.get(f"/cabinet-profiles/{p['id']}/history").json():
        assert _has_offset(e["occurred_at"])


def test_image_variant_urls_resolve(client):
    p = mk(client)
    _put(client, p["id"], png(2000, 1000))
    img = client.get(f"/cabinet-profiles/{p['id']}").json()["front_image"]
    for key, variant, ct, longest in (("url", None, "image/png", 2000), ("thumb_url", "thumb", "image/webp", 512),
                                      ("tex_url", "tex", "image/webp", 1024)):
        u = img[key]
        assert u.startswith(f"/cabinet-profile-images/{p['id']}/front?v=")
        assert (f"variant={variant}" in u) if variant else ("variant=" not in u)
        r = client.get(u)
        assert r.status_code == 200 and r.headers["content-type"] == ct
        assert r.headers["cache-control"] == "private, max-age=31536000, immutable" and r.headers["etag"]
        from PIL import Image
        import io
        assert max(Image.open(io.BytesIO(r.content)).size) == longest
    bare = client.get(f"/cabinet-profile-images/{p['id']}/front?variant=thumb")  # no ?v= -> revalidate
    assert bare.headers["cache-control"] == "private, max-age=300, must-revalidate"


def test_list_paginates(client):
    for i in range(5):
        mk(client, model=f"M{i}")
    r = client.get("/cabinet-profiles?limit=2&offset=1")
    assert r.headers["X-Total-Count"] == "5" and [x["model"] for x in r.json()] == ["M1", "M2"]


INT_FIELDS = ("width_mm", "height_mm", "depth_mm", "usable_width_mm", "usable_depth_mm", "rail_depth_min_mm",
              "rail_depth_max_mm")


@pytest.mark.parametrize("field", INT_FIELDS)
def test_size_beyond_integer_range_is_422_on_both_dbs(client, field):
    r = client.post("/cabinet-profiles", json={"manufacturer": "A", "model": f"Huge-{field}", field: 3_000_000_000})
    assert r.status_code == 422 and code(r) == "invalid_dimension" and r.json()["detail"]["fields"] == [field]
    p = mk(client, model=f"Edit-{field}")
    r = client.patch(f"/cabinet-profiles/{p['id']}", json={field: 2_147_483_648})
    assert r.status_code == 422 and r.json()["detail"]["fields"] == [field]
    r = client.patch(f"/cabinet-profiles/{p['id']}", json={"unit": "in", field: 100_000_000})  # 2.54e9 mm
    assert r.status_code == 422 and r.json()["detail"]["fields"] == [field]


def test_weight_beyond_numeric_range_is_422_on_both_dbs(client):
    r = client.post("/cabinet-profiles", json={"manufacturer": "A", "model": "W", "weight_capacity_kg": 1_000_000})
    assert r.status_code == 422 and r.json()["detail"]["fields"] == ["weight_capacity_kg"]
    p = mk(client, model="W2", weight_capacity_kg=999_999.99)
    assert p["weight_capacity_kg"] == 999_999.99
    r = client.patch(f"/cabinet-profiles/{p['id']}", json={"weight_capacity_kg": 1_000_000.5})
    assert r.status_code == 422 and code(r) == "invalid_dimension"


def test_huge_inch_value_is_422_not_500(client):
    r = client.post("/cabinet-profiles", json={"manufacturer": "A", "model": "Inf", "unit": "in", "width_mm": 1e307})
    assert r.status_code == 422 and code(r) == "invalid_dimension"


ISO_UTC = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$"


def _strings(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _strings(v)
    elif isinstance(obj, str):
        yield obj


def test_history_datetimes_iso_utc(client, engine):
    import re
    p = mk(client, **COMPLETE)
    pid = p["id"]
    for step in ("publish", "retire", "unretire"):
        client.post(f"/cabinet-profiles/{pid}/{step}")
    with Session(engine) as s:  # an old-format row (naive, space separator) is normalised on read
        from app.modules.audit.service import record_audit
        record_audit(s, None, "cabinet_profile.update", "cabinet_profile", pid,
                     before={"retired_at": "2026-11-04 01:12:31.331192"}, after={"retired_at": None})
        s.commit()
    assert client.delete(f"/cabinet-profiles/{pid}").status_code == 204
    ev = client.get(f"/cabinet-profiles/{pid}/history?limit=100").json()
    assert {"cabinet_profile.create", "cabinet_profile.publish", "cabinet_profile.retire",
            "cabinet_profile.unretire", "cabinet_profile.delete"} <= {e["action"] for e in ev}
    dts = []
    for e in ev:
        assert re.match(ISO_UTC, e["occurred_at"]), e["occurred_at"]
        for side in ("before", "after"):
            dts += [v for v in _strings(e[side] or {}) if re.match(r"^\d{4}-\d{2}-\d{2}[ T]\d", v)]
    assert len(dts) >= 4  # published_at/retired_at in the listener diffs + delete snapshot (created/updated_at are not snapshotted)
    bad = [v for v in dts if not re.match(ISO_UTC, v)]
    assert not bad, bad
    assert "2026-11-04T01:12:31.331192Z" in dts
