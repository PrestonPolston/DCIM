import itertools

import pytest


def make_rack(client, u_height=53, name="R01"):
    site = client.post("/sites", json={"name": "DC1"}).json()
    hall = client.post("/halls", json={"site_id": site["id"], "name": "Hall A"}).json()
    row = client.post("/rows", json={"hall_id": hall["id"], "name": "Row 1"}).json()
    return client.post("/racks", json={"row_id": row["id"], "name": name, "u_height": u_height}).json()


def test_hierarchy_crud(client):
    site = client.post("/sites", json={"name": "DC1", "address": "1 Main St"}).json()
    assert client.patch(f"/sites/{site['id']}", json={"name": "DC-1"}).json()["name"] == "DC-1"
    hall = client.post("/halls", json={"site_id": site["id"], "name": "A"}).json()
    row = client.post("/rows", json={"hall_id": hall["id"], "name": "1"}).json()
    rack = client.post("/racks", json={"row_id": row["id"], "name": "R1"}).json()
    assert rack["u_height"] == 53  # standard cabinet
    assert client.get(f"/racks/{rack['id']}").json()["row_id"] == row["id"]

    # Parent can't be deleted while it has children
    r = client.delete(f"/sites/{site['id']}")
    assert r.status_code == 409 and "halls" in r.json()["detail"]

    for path, obj in [("racks", rack), ("rows", row), ("halls", hall), ("sites", site)]:
        assert client.delete(f"/{path}/{obj['id']}").status_code == 204
        assert client.get(f"/{path}/{obj['id']}").status_code == 404


def test_missing_parent_and_duplicate_name(client):
    assert client.post("/halls", json={"site_id": 999, "name": "A"}).status_code == 404
    client.post("/sites", json={"name": "DC1"})
    r = client.post("/sites", json={"name": "DC1"})
    assert r.status_code == 409


def test_pagination_and_filters(client):
    s1 = client.post("/sites", json={"name": "Alpha"}).json()
    s2 = client.post("/sites", json={"name": "Beta"}).json()
    for i in range(5):
        client.post("/halls", json={"site_id": s1["id"], "name": f"Hall {i}"})
    client.post("/halls", json={"site_id": s2["id"], "name": "Other"})

    r = client.get("/halls", params={"limit": 2, "offset": 1})
    assert [h["name"] for h in r.json()] == ["Hall 1", "Hall 2"]
    assert r.headers["X-Total-Count"] == "6"

    r = client.get("/halls", params={"site_id": s2["id"]})
    assert [h["name"] for h in r.json()] == ["Other"]
    assert client.get("/sites", params={"q": "alp"}).json()[0]["name"] == "Alpha"
    assert client.get("/halls", params={"limit": 0}).status_code == 422


def test_device_type_crud(client):
    r = client.post("/device-types", json={"manufacturer": "Dell", "name": "R650", "u_height": 1})
    dt = r.json()
    assert r.status_code == 201 and dt["is_full_depth"] is True
    assert client.post("/device-types", json={"manufacturer": "Dell", "name": "R650"}).status_code == 409
    assert client.get("/device-types", params={"manufacturer": "Dell"}).json()[0]["id"] == dt["id"]
    assert client.patch(f"/device-types/{dt['id']}", json={"u_height": 2}).json()["u_height"] == 2
    assert client.delete(f"/device-types/{dt['id']}").status_code == 204


# ---- Rack placement ----
@pytest.fixture
def rack(client):
    return make_rack(client, u_height=10)


COMPLETE = {"width_mm": 482.6, "height_mm": 44.0, "depth_mm": 600.0, "power_type": "AC", "mounting": "rack_19in"}


def tiny_png() -> bytes:
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (8, 4), (90, 90, 90)).save(buf, "PNG")
    return buf.getvalue()


def publish_profile(client, type_id, profile_id, fields=COMPLETE):
    """Make a profile publishable (template fields, type asset_type, front image) and publish it."""
    t = client.get(f"/device-types/{type_id}").json()
    if not t.get("asset_type"):
        client.patch(f"/device-types/{type_id}", json={"asset_type": "server"})
    base = f"/device-types/{type_id}/profiles/{profile_id}"
    if t.get("asset_type") == "switch" and "orientation" not in fields:
        fields = {**fields, "orientation": "port_front"}  # D58: switches need one to publish
    client.patch(base, json=fields)
    client.put(f"{base}/images/front", content=tiny_png(), headers={"content-type": "image/png"})
    client.put(f"{base}/images/rear", content=tiny_png(), headers={"content-type": "image/png"})
    r = client.post(f"{base}/publish")
    assert r.status_code == 200, r.text
    return r.json()


def complete_default(client, dt):
    """Placement needs a complete profile: give the type's auto-created default profile dims + AC/DC."""
    if "id" in dt:
        prof = next(p for p in client.get(f"/device-types/{dt['id']}/profiles").json() if p["is_default"])
        publish_profile(client, dt["id"], prof["id"])
    return dt


def dtype(client, u, full_depth=True, name=None):
    return complete_default(client, client.post(
        "/device-types",
        json={"manufacturer": "Acme", "name": name or f"{u}U-{full_depth}", "u_height": u,
              "is_full_depth": full_depth},
    ).json())


_host_ids = itertools.count(1)


def place(client, rack, dt, pos, face="front", host=None):
    host = host or f"h{next(_host_ids)}"
    return client.post("/devices", json={
        "host_name": host, "rack_id": rack["id"], "device_type_id": dt["id"],
        "position_u": pos, "face": face,
    })


def test_place_fits_and_bounds(client, rack):
    two_u = dtype(client, 2)
    assert place(client, rack, two_u, 9).status_code == 201  # U9-U10, top of 10U rack
    r = place(client, rack, two_u, 10)
    assert r.status_code == 409 and "exceeds cabinet 'R01' height of 10U" in r.json()["detail"]
    assert place(client, rack, two_u, 0).status_code == 422


def test_overlap_rejected_with_clear_message(client, rack):
    two_u = dtype(client, 2)
    assert place(client, rack, two_u, 1, host="a").status_code == 201
    r = place(client, rack, two_u, 2, host="b")
    assert r.status_code == 409
    assert "overlaps device 'a'" in r.json()["detail"] and "U1-U2" in r.json()["detail"]
    assert place(client, rack, two_u, 3, host="c").status_code == 201  # adjacent ok


def test_half_depth_front_and_rear_can_share_u(client, rack):
    half = dtype(client, 1, full_depth=False)
    full = dtype(client, 1, full_depth=True)
    assert place(client, rack, half, 5, "front").status_code == 201
    assert place(client, rack, half, 5, "rear").status_code == 201
    assert place(client, rack, half, 5, "front").status_code == 409
    assert place(client, rack, half, 6, "front").status_code == 201
    assert place(client, rack, full, 6, "rear").status_code == 409  # full-depth blocks both faces


def test_move_device_revalidates_and_ignores_itself(client, rack):
    two_u = dtype(client, 2)
    a = place(client, rack, two_u, 1, host="a").json()
    b = place(client, rack, two_u, 5, host="b").json()
    assert client.patch(f"/devices/{a['id']}", json={"position_u": 2}).status_code == 200
    r = client.patch(f"/devices/{a['id']}", json={"position_u": 4})
    assert r.status_code == 409
    assert client.get(f"/devices/{a['id']}").json()["position_u"] == 2  # unchanged
    assert client.patch(f"/devices/{b['id']}", json={"rack_id": None, "position_u": None}).status_code == 200


def test_placement_requires_fields(client, rack):
    r = client.post("/devices", json={"host_name": "x", "rack_id": rack["id"]})
    assert r.status_code == 422
    assert client.post("/devices", json={"host_name": "x", "position_u": 3}).status_code == 422
    dt = dtype(client, 1)
    r = client.post("/devices", json={"host_name": "x", "rack_id": 999, "device_type_id": dt["id"], "position_u": 1})
    assert r.status_code == 404


def test_rack_shrink_and_type_resize_guarded(client, rack):
    four_u = dtype(client, 4)
    place(client, rack, four_u, 5)  # U5-U8
    r = client.patch(f"/racks/{rack['id']}", json={"u_height": 6})
    assert r.status_code == 409 and "U8" in r.json()["detail"]
    assert client.patch(f"/racks/{rack['id']}", json={"u_height": 8}).status_code == 200
    assert client.patch(f"/device-types/{four_u['id']}", json={"u_height": 2}).status_code == 409
    # deleting a rack decommissions (and unracks) its devices instead of blocking
    r = client.delete(f"/racks/{rack['id']}")
    assert r.status_code == 204 and r.headers["X-Decommissioned-Count"] == "1"


def test_device_filters(client, rack):
    dt = dtype(client, 1)
    place(client, rack, dt, 1, host="web-01")
    place(client, rack, dt, 2, host="db-01")
    client.post("/devices", json={"host_name": "spare", "status": "active"})
    assert client.get("/devices", params={"rack_id": rack["id"]}).headers["X-Total-Count"] == "2"
    assert [d["host_name"] for d in client.get("/devices", params={"q": "WEB"}).json()] == ["web-01"]
    assert [d["host_name"] for d in client.get("/devices", params={"status": "active"}).json()] == ["spare"]


def test_host_name_unique_per_rack_not_global(client, rack):
    dt = dtype(client, 1)
    assert place(client, rack, dt, 1, host="web-01").status_code == 201
    r = place(client, rack, dt, 2, host="WEB-01")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "hostname_conflict" and "already exists in cabinet 'R01'" in r.json()["detail"]["message"]
    other = client.post("/racks", json={"row_id": rack["row_id"], "name": "R02"}).json()
    assert place(client, other, dt, 1, host="web-01").status_code == 201
    # unracked devices may share names
    assert client.post("/devices", json={"host_name": "web-01"}).status_code == 201
    assert client.post("/devices", json={"host_name": "web-01"}).status_code == 201
