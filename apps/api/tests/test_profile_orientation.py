"""D58 / REVIEW_ORIENTATION: profile orientation (port_front | power_front), switch publish rule, swap_faces."""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.modules.audit.models import AuditEventRow
from app.modules.images.models import ProfileImageRow
from tests.test_locations import COMPLETE, make_rack
from tests.test_profile_images import png


def _switch(client, name="SW-48", asset="switch"):
    t = client.post("/device-types", json={"manufacturer": "Acme", "name": name, "u_height": 1,
                                           "asset_type": asset}).json()
    p = client.post(f"/device-types/{t['id']}/profiles", json={"name": "Std"}).json()
    base = f"/device-types/{t['id']}/profiles/{p['id']}"
    client.patch(base, json=COMPLETE)
    front = client.put(f"{base}/images/front", content=png(40, 10), headers={"content-type": "image/png"}).json()
    rear = client.put(f"{base}/images/rear", content=png(30, 10), headers={"content-type": "image/png"}).json()
    return t, p, base, front, rear


def test_switch_needs_orientation_to_publish(client):
    t, p, base, *_ = _switch(client)
    r = client.post(f"{base}/publish")
    assert r.status_code == 422 and r.json()["detail"]["missing"] == ["orientation"]
    assert client.patch(base, json={"orientation": "sideways"}).status_code == 422
    assert client.patch(base, json={"orientation": "port_front"}).json()["orientation"] == "port_front"
    assert client.post(f"{base}/publish").status_code == 200
    # non-switch: optional
    t2, p2, base2, *_ = _switch(client, "SRV", "server")
    assert client.post(f"{base2}/publish").status_code == 200
    assert client.get(base2).json()["orientation"] is None
    assert [x["id"] for x in client.get("/profiles", params={"orientation": "port_front"}).json()] == [p["id"]]


def test_published_switch_without_orientation_not_usable(client, engine):
    t, p, base, *_ = _switch(client, "Later", "server")
    assert client.post(f"{base}/publish").status_code == 200
    rack = make_rack(client)
    old = client.post("/devices", json={"host_name": "old", "profile_id": p["id"], "rack_id": rack["id"],
                                        "position_u": 1}).json()
    client.patch(f"/device-types/{t['id']}", json={"asset_type": "switch"})  # type becomes a switch later
    prof = client.get(base).json()
    assert prof["status"] == "published" and not prof["usable"] and prof["usable_issues"] == ["orientation_missing"]
    r = client.post("/devices", json={"host_name": "new", "profile_id": p["id"]})
    assert r.status_code == 422 and r.json()["detail"]["issues"] == ["orientation_missing"]
    assert client.patch(f"/devices/{old['id']}", json={"notes": "fine"}).status_code == 200  # not locked
    assert p["id"] not in [x["id"] for x in client.get("/profiles", params={"usable": "true"}).json()]
    # setting the missing orientation (allowed even in use) makes it usable
    assert client.patch(base, json={"orientation": "power_front"}).status_code == 200
    assert client.get(base).json()["usable"] is True
    # changing it once set, while in use -> clone with swap_faces instead
    r = client.patch(base, json={"orientation": "port_front"})
    assert r.status_code == 409 and r.json()["detail"]["fields"] == ["orientation"]


def test_clone_swap_faces(client, engine):
    t, p, base, front, rear = _switch(client)
    client.patch(base, json={"orientation": "port_front"})
    client.post(f"{base}/publish")
    r = client.post(f"/profiles/{p['id']}/clone", json={"swap_faces": True})
    assert r.status_code == 201, r.text
    new = r.json()
    assert new["name"] == "Std (power front)" and new["orientation"] == "power_front" and new["status"] == "draft"
    assert new["front_image"]["width_px"] == 30 and new["rear_image"]["width_px"] == 40  # swapped
    assert new["front_image"]["thumb_url"] and new["front_image"]["url"] != rear["url"]
    with Session(engine) as s:
        rows = s.exec(select(ProfileImageRow.face, ProfileImageRow.variant, ProfileImageRow.sha256)
                      .where(ProfileImageRow.profile_id == new["id"])).all()
        assert sorted((f, v) for f, v, _ in rows) == [("front", "original"), ("front", "tex"), ("front", "thumb"),
                                                      ("rear", "original"), ("rear", "tex"), ("rear", "thumb")]
        assert dict(((f, v), sh) for f, v, sh in rows)[("front", "original")] == rear["sha256"]
        ev = s.exec(select(AuditEventRow).where(AuditEventRow.action == "profile.clone")).one()
        assert '"swap_faces": true' in ev.after_json
    # swapping back replaces the suffix (no stacking); collision -> " 2"
    back = client.post(f"/profiles/{new['id']}/clone", json={"swap_faces": True}).json()
    assert back["name"] == "Std (port front)" and back["orientation"] == "port_front"
    again = client.post(f"/profiles/{p['id']}/clone", json={"swap_faces": True}).json()
    assert again["name"] == "Std (power front) 2"
    # two profiles of a type may share an orientation
    assert client.patch(f"/device-types/{t['id']}/profiles/{again['id']}", json={"orientation": "power_front"}).status_code == 200


def test_orientation_on_device_elevation_and_csv(client):
    t, p, base, *_ = _switch(client)
    client.patch(base, json={"orientation": "port_front"})
    client.post(f"{base}/publish")
    v2 = client.post(f"/profiles/{p['id']}/clone", json={"swap_faces": True}).json()
    vb = f"/device-types/{t['id']}/profiles/{v2['id']}"
    assert client.post(f"{vb}/publish").status_code == 200
    rack = make_rack(client)
    d = client.post("/devices", json={"host_name": "sw1", "profile_id": v2["id"], "rack_id": rack["id"],
                                      "position_u": 3}).json()
    assert d["orientation"] == "power_front"
    elev = client.get(f"/racks/{rack['id']}/elevation").json()["devices"][0]
    assert elev["orientation"] == "power_front"
    csv = ("host_name,manufacturer,model,orientation\n"
           "a,Acme,SW-48,\n"            # two published variants, blank -> error
           "b,Acme,SW-48,power_front\n"
           "c,Acme,SW-48,sideways\n")
    body = client.post("/devices/import?dry_run=true", content=csv, headers={"content-type": "text/csv"}).json()
    errs = {e["row"]: e["details"][0]["code"] for e in body["errors"]}
    assert errs == {2: "orientation_required", 4: "invalid_value"}, body
    ok = client.post("/devices/import?dry_run=false", content="host_name,manufacturer,model,orientation\n"
                     "b,Acme,SW-48,power_front\n", headers={"content-type": "text/csv"}).json()
    assert ok["created"] == 1
    b = client.get("/devices", params={"q": "b"}).json()
    assert any(x["host_name"] == "b" and x["profile_id"] == v2["id"] for x in b)
    export = client.get("/devices/export").text.splitlines()
    assert "orientation" in export[0].split(",")


def test_orientation_check_constraint(engine):
    with pytest.raises(IntegrityError):
        with engine.begin() as c:
            c.execute(text("INSERT INTO device_types(manufacturer, name, u_height, is_full_depth) VALUES ('x','y',1,true)"))
            c.execute(text("INSERT INTO device_type_profiles(device_type_id, name, is_default, u_height, is_full_depth, "
                           "orientation) VALUES ((SELECT max(id) FROM device_types), 'z', false, 1, true, 'sideways')"))
