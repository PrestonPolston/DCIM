from tests.test_locations import dtype, make_rack

RAW = {"X-Test-Raw": "1"}


def default_profile(client, t):
    return next(p for p in client.get(f"/device-types/{t['id']}/profiles").json() if p["is_default"])


def test_drag_to_rack_same_rules_as_post_devices(client, client_as):
    rack = make_rack(client)
    t2 = dtype(client, 2)
    prof = default_profile(client, t2)
    url = f"/racks/{rack['id']}/devices"
    r = client.post(url, json={"host_name": "web-1", "profile_id": prof["id"], "position_u": 10, "face": "front"})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["rack_id"] == rack["id"] and d["device_type_id"] == t2["id"] and d["status"] == "install"
    # overlap -> same 409 as POST /devices
    clash = {"host_name": "web-2", "profile_id": prof["id"], "position_u": 11}
    a = client.post(url, json=clash)
    b = client.post("/devices", json={**clash, "rack_id": rack["id"]})
    assert a.status_code == b.status_code == 409 and a.json() == b.json()
    # off the top -> same 422
    top = {"host_name": "web-3", "profile_id": prof["id"], "position_u": 53}
    assert client.post(url, json=top).json() == client.post("/devices", json={**top, "rack_id": rack["id"]}).json()
    # draft profile -> profile_not_published; profile_id is required; rack_id not accepted in the body
    raw = client.post("/device-types", json={"manufacturer": "Acme", "name": "bare"}).json()
    r = client.post(url, json={"host_name": "x", "profile_id": default_profile(client, raw)["id"], "position_u": 1})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "profile_not_published"
    assert client.post(url, json={"host_name": "x", "position_u": 1}, headers=RAW).status_code == 422
    assert client.post(url, json={"host_name": "x", "profile_id": prof["id"], "position_u": 1,
                                  "rack_id": 5}).status_code == 422
    # missing rack, RBAC
    assert client.post("/racks/99999/devices", json={"host_name": "x", "profile_id": prof["id"],
                                                     "position_u": 1}).status_code == 404
    assert client_as("read-only").post(url, json={"host_name": "x", "profile_id": prof["id"],
                                                  "position_u": 30}).status_code == 403
    # POST /devices and PATCH still work
    assert client.post("/devices", json={"host_name": "db-1", "device_type_id": t2["id"], "rack_id": rack["id"],
                                         "position_u": 20}).status_code == 201
    assert client.patch(f"/devices/{d['id']}", json={"position_u": 30}).json()["position_u"] == 30
