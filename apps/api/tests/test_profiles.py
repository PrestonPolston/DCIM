from tests.test_locations import COMPLETE, publish_profile


def make_type(client, u=2):
    from tests.test_locations import complete_default
    return complete_default(client, client.post(
        "/device-types", json={"manufacturer": "Dell", "name": f"R{u}", "u_height": u}).json())


def test_default_profile_created_and_mirrors_u_height(client):
    dt = client.post("/device-types", json={"manufacturer": "Dell", "name": "R2", "u_height": 2}).json()
    profiles = client.get(f"/device-types/{dt['id']}/profiles").json()
    assert [(p["name"], p["is_default"], p["u_height"], p["status"]) for p in profiles] == [
        ("default", True, 2, "draft")]
    client.patch(f"/device-types/{dt['id']}", json={"u_height": 3})
    assert client.get(f"/device-types/{dt['id']}/profiles").json()[0]["u_height"] == 3
    publish_profile(client, dt["id"], profiles[0]["id"])
    r = client.patch(f"/device-types/{dt['id']}", json={"u_height": 4})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "profile_published"
    assert client.patch(f"/device-types/{dt['id']}", json={"asset_type": None}).status_code == 409


def test_profile_crud_and_single_default(client):
    dt = make_type(client)
    r = client.post(f"/device-types/{dt['id']}/profiles", json={
        "name": "with-rails", "is_default": True, "depth_mm": 750,
        "ports": [{"name": "eth0", "kind": "ethernet"}], "model_refs": {"glb": "https://x/r650.glb"}})
    p = r.json()
    assert r.status_code == 201 and p["ports"][0]["name"] == "eth0" and p["depth_mm"] == 750
    defaults = [x["name"] for x in client.get(f"/device-types/{dt['id']}/profiles").json() if x["is_default"]]
    assert defaults == ["with-rails"]
    assert client.post(f"/device-types/{dt['id']}/profiles", json={"name": "with-rails"}).status_code == 409
    assert client.post(f"/device-types/{dt['id']}/profiles", json={"name": "x", "depth_mm": 0}).status_code == 422
    other = make_type(client, 1)
    assert client.get(f"/device-types/{other['id']}/profiles/{p['id']}").status_code == 404
    assert client.patch(f"/device-types/{dt['id']}/profiles/{p['id']}", json={"name": "rails"}).json()["name"] == "rails"


def test_device_profile_override(client):
    dt, other = make_type(client), make_type(client, 1)
    p = client.post(f"/device-types/{dt['id']}/profiles", json={"name": "alt", **COMPLETE}).json()
    publish_profile(client, dt["id"], p["id"])
    other_p = client.get(f"/device-types/{other['id']}/profiles").json()[0]
    default_p = next(x for x in client.get(f"/device-types/{dt['id']}/profiles").json() if x["is_default"])
    # only a type given: the device stores the type's default profile
    assert client.post("/devices", json={"host_name": "a", "device_type_id": dt["id"]}).json()["profile_id"] == default_p["id"]
    d = client.post("/devices", json={"host_name": "b", "device_type_id": dt["id"], "profile_id": p["id"]}).json()
    assert d["profile_id"] == p["id"]
    r = client.post("/devices", json={"host_name": "c", "device_type_id": dt["id"], "profile_id": other_p["id"]})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "profile_type_mismatch"
    # p1_18: a profile used by any device can't be deleted (unplaced too)
    r = client.delete(f"/device-types/{dt['id']}/profiles/{p['id']}")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "profile_in_use"
    assert client.get(f"/devices/{d['id']}").json()["profile_id"] == p["id"]


def test_profile_used_by_placed_device_cannot_be_deleted(client):
    from tests.test_locations import make_rack
    dt = make_type(client)
    p = client.post(f"/device-types/{dt['id']}/profiles", json={"name": "alt", **COMPLETE}).json()
    publish_profile(client, dt["id"], p["id"])
    rack = make_rack(client)
    d = client.post("/devices", json={"host_name": "x", "rack_id": rack["id"], "position_u": 1,
                                      "profile_id": p["id"]}).json()
    assert d["device_type_id"] == dt["id"]  # filled from the profile
    r = client.delete(f"/device-types/{dt['id']}/profiles/{p['id']}")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "profile_in_use"


def test_asset_type_on_existing_models(client, client_as):
    from tests.test_locations import COMPLETE, tiny_png
    t = client.post("/device-types", json={"manufacturer": "Old", "name": "NoType", "u_height": 1}).json()
    assert t["asset_type"] is None
    p = next(p for p in client.get(f"/device-types/{t['id']}/profiles").json() if p["is_default"])
    base = f"/device-types/{t['id']}/profiles/{p['id']}"
    client.patch(base, json=COMPLETE)
    client.put(f"{base}/images/front", content=tiny_png(), headers={"content-type": "image/png"})
    client.put(f"{base}/images/rear", content=tiny_png(), headers={"content-type": "image/png"})
    r = client.get(base).json()["readiness"]
    assert r["missing"] == ["asset_type"] and "no asset type" in r["messages"]["asset_type"]
    bad = client.post(f"{base}/publish")
    assert bad.status_code == 422 and bad.json()["detail"]["missing"] == ["asset_type"]
    assert "PATCH /device-types" in bad.json()["detail"]["messages"]["asset_type"]
    tech, ro = client_as("technician"), client_as("read-only")
    assert ro.patch(f"/device-types/{t['id']}", json={"asset_type": "server"}).status_code == 403
    assert client.patch(f"/device-types/{t['id']}", json={"asset_type": "toaster"}).status_code == 422
    r = tech.patch(f"/device-types/{t['id']}", json={"u_height": 2})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "device_type_change_requires_admin"
    assert tech.patch(f"/device-types/{t['id']}", json={"asset_type": "server"}).json()["asset_type"] == "server"
    assert client.get(base).json()["readiness"] == {"ready": True, "missing": [], "messages": {}, "flags": []}
    assert client.post(f"{base}/publish").status_code == 200


def test_add_profile_sets_model_asset_type(client, client_as):
    t = client.post("/device-types", json={"manufacturer": "Old", "name": "NoType2", "u_height": 1}).json()
    tech = client_as("technician")
    r = tech.post(f"/device-types/{t['id']}/profiles", json={"name": "v1", "asset_type": "storage"})
    assert r.status_code == 201, r.text
    assert client.get(f"/device-types/{t['id']}").json()["asset_type"] == "storage"
    r = tech.post(f"/device-types/{t['id']}/profiles", json={"name": "v2", "asset_type": "server"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "asset_type_mismatch"
    assert tech.post(f"/device-types/{t['id']}/profiles", json={"name": "v3", "asset_type": "storage"}).status_code == 201
    assert tech.post(f"/device-types/{t['id']}/profiles", json={"name": "v4", "asset_type": "nope"}).status_code == 422


def test_device_profile_unit_input(client):
    """ADMIN_INPUT_PLAN rev 3 §4c: device profiles accept "unit": "in"; stored/returned in mm (0.1 mm)."""
    t = client.post("/device-types", json={"manufacturer": "Dell", "name": "U1", "u_height": 1}).json()
    r = client.post(f"/device-types/{t['id']}/profiles", json={"name": "in", "unit": "in", "width_mm": 17.25,
                                                               "depth_mm": 29.0})
    assert r.status_code == 201, r.text
    assert (r.json()["width_mm"], r.json()["depth_mm"]) == (438.2, 736.6) and "unit" not in r.json()
    pid = r.json()["id"]
    r = client.patch(f"/device-types/{t['id']}/profiles/{pid}", json={"unit": "in", "height_mm": 1.75})
    assert r.status_code == 200 and r.json()["height_mm"] == 44.5
    r = client.patch(f"/device-types/{t['id']}/profiles/{pid}", json={"unit": "mm", "height_mm": 43.2})
    assert r.json()["height_mm"] == 43.2
    r = client.patch(f"/device-types/{t['id']}/profiles/{pid}", json={"unit": "ft", "height_mm": 1})
    assert r.status_code == 422 and r.json()["detail"][0]["type"] == "invalid_unit"


def test_profile_dims_are_floats_not_decimal(client, engine):
    """Numeric(asdecimal=False): the ORM hands back float, so responses serialize without Decimal warnings."""
    import warnings
    from sqlmodel import Session
    from app.modules.device_types.models import DeviceTypeProfileRow
    t = client.post("/device-types", json={"manufacturer": "Dell", "name": "F1", "u_height": 1}).json()
    pid = client.post(f"/device-types/{t['id']}/profiles", json={"name": "f", "unit": "in", "width_mm": 17.25,
                                                                 "weight_kg": 12.5}).json()["id"]
    with Session(engine) as s:
        row = s.get(DeviceTypeProfileRow, pid)
        assert type(row.width_mm) is float and type(row.weight_kg) is float
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert client.get(f"/device-types/{t['id']}/profiles/{pid}").json()["width_mm"] == 438.2
