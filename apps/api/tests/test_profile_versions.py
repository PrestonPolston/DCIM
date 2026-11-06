from tests.test_locations import dtype, make_rack, publish_profile


def default_profile(client, t):
    return next(p for p in client.get(f"/device-types/{t['id']}/profiles").json() if p["is_default"])


def test_clone_adopt_retire_flow(client):
    rack = make_rack(client)
    t = dtype(client, 1, full_depth=False)
    old = default_profile(client, t)
    a = client.post("/devices", json={"host_name": "a", "profile_id": old["id"], "rack_id": rack["id"],
                                      "position_u": 1, "face": "front"}).json()
    b = client.post("/devices", json={"host_name": "b", "profile_id": old["id"], "rack_id": rack["id"],
                                      "position_u": 1, "face": "rear"}).json()
    spare = client.post("/devices", json={"host_name": "s", "profile_id": old["id"]}).json()
    # in use + published: template fields frozen
    assert client.patch(f"/device-types/{t['id']}/profiles/{old['id']}",
                        json={"depth_mm": 999}).status_code == 409
    r = client.post(f"/profiles/{old['id']}/clone")
    assert r.status_code == 201
    new = r.json()
    assert new["status"] == "draft" and new["version"] == 2 and new["supersedes_profile_id"] == old["id"]
    assert new["front_image"] and new["readiness"]["ready"] and not new["is_default"]
    # the new version becomes full depth -> a and b (front/rear at U1) can't both use it
    base = f"/device-types/{t['id']}/profiles/{new['id']}"
    assert client.patch(base, json={"is_full_depth": True, "depth_mm": 750}).status_code == 200  # unused draft
    assert client.post(f"/profiles/{new['id']}/adopt", json={"all": True}).json()["detail"]["code"] == \
        "profile_not_published"
    assert client.post(f"{base}/publish").status_code == 200
    r = client.post(f"/profiles/{new['id']}/adopt", json={"all": True})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "adopt_conflict"
    assert [c["device_id"] for c in r.json()["detail"]["conflicts"]] == [a["id"], b["id"]]  # they block each other
    assert {d["profile_id"] for d in client.get("/devices").json()} == {old["id"]}  # nothing changed
    # fit-check agrees with the real result
    fc = client.post(f"/racks/{rack['id']}/fit-check", json={"profile_id": new["id"], "position_u": 1,
                                                             "device_id": a["id"]}).json()
    assert fc["fits"] is False and fc["conflicts"][0]["status"] == 409
    assert client.post(f"/racks/{rack['id']}/fit-check", json={"profile_id": new["id"],
                                                               "position_u": 5}).json() == {"fits": True, "conflicts": []}
    # move b out of the way, then adopt all
    assert client.patch(f"/devices/{b['id']}", json={"position_u": 10}).status_code == 200
    r = client.post(f"/profiles/{new['id']}/adopt", json={"all": True})
    assert r.status_code == 200 and r.json()["moved"] == 3
    assert {d["profile_id"] for d in client.get("/devices").json()} == {new["id"]}
    assert client.get(f"/devices/{spare['id']}").json()["profile_id"] == new["id"]
    # retire the old one: no new devices on it
    r = client.post(f"/profiles/{old['id']}/retire")
    assert r.status_code == 200 and r.json()["status"] == "retired" and r.json()["retired_at"]
    r = client.post("/devices", json={"host_name": "z", "profile_id": old["id"]})
    assert r.status_code == 422 and r.json()["detail"]["profile_status"] == "retired"
    assert client.post(f"/profiles/{old['id']}/publish").json()["detail"]["code"] == "profile_retired"
    assert client.post(f"/profiles/{new['id']}/clone", json={"name": "v3"}).json()["version"] == 3


def test_in_use_draft_fit_edit_refused_and_adopt_by_ids(client, engine):
    from sqlmodel import Session
    from app.modules.devices.models import DeviceRow
    raw = client.post("/device-types", json={"manufacturer": "Acme", "name": "bare"}).json()
    draft = default_profile(client, raw)
    with Session(engine) as s:  # PD5-style legacy device linked to a draft
        d = DeviceRow(host_name="legacy", device_type_id=raw["id"], profile_id=draft["id"], status="active",
                      needs_review=True, needs_review_reason="profile_not_published")
        s.add(d)
        s.commit()
        dev_id = d.id
    url = f"/device-types/{raw['id']}/profiles/{draft['id']}"
    assert client.patch(url, json={"depth_mm": 500}).status_code == 200  # filling in a missing value is fine
    r = client.patch(url, json={"depth_mm": 600})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "profile_in_use"
    assert r.json()["detail"]["device_count"] == 1
    other = client.post(f"/device-types/{raw['id']}/profiles", json={"name": "good"}).json()
    publish_profile(client, raw["id"], other["id"])
    r = client.post(f"/profiles/{other['id']}/adopt", json={"device_ids": [dev_id]})
    assert r.status_code == 200, r.text
    d = client.get(f"/devices/{dev_id}").json()
    assert d["profile_id"] == other["id"] and d["needs_review"] is False
    assert client.post(f"/profiles/{other['id']}/adopt", json={"device_ids": [424242]}).status_code == 404
    mismatch = dtype(client, 1, name="other-type")
    m = client.post("/devices", json={"host_name": "m", "device_type_id": mismatch["id"]}).json()
    r = client.post(f"/profiles/{other['id']}/adopt", json={"device_ids": [m["id"]]})
    assert r.status_code == 409 and r.json()["detail"]["conflicts"][0]["code"] == "profile_type_mismatch"


def test_roles(client, client_as):
    t = dtype(client, 1)
    p = default_profile(client, t)
    tech = client_as("technician")
    assert tech.post(f"/profiles/{p['id']}/clone").status_code == 403
    assert tech.post(f"/profiles/{p['id']}/retire").status_code == 403
    assert client_as("read-only").post(f"/profiles/{p['id']}/adopt", json={"all": True}).status_code == 403
