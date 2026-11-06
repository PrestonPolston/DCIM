from sqlalchemy import event

from tests.test_locations import dtype, make_rack


def _setup(client, cabinets):
    first = make_rack(client, name="C01")
    client.patch(f"/racks/{first['id']}", json={"pos_x": 1})
    racks = [first] + [client.post("/racks", json={"row_id": first["row_id"], "name": f"C{i:02d}", "pos_x": i})
                       .json() for i in range(2, cabinets + 1)]
    t = dtype(client, 1)
    for r in racks:
        for u in (1, 3):
            assert client.post("/devices", json={"host_name": f"{r['name']}-{u}", "device_type_id": t["id"],
                                                 "rack_id": r["id"], "position_u": u}).status_code == 201
    return first["row_id"], racks


def test_row_front_lists_cabinets_with_items(client, client_as):
    row_id, racks = _setup(client, 3)
    a, b = (client.get("/devices", params={"q": n}).json()[0] for n in ("C01-1", "C02-1"))
    from tests.test_connections import connect
    assert connect(client, a, "eth0", b, "eth0").status_code == 201
    r = client_as("read-only").get(f"/rows/{row_id}/front")
    assert r.status_code == 200
    body = r.json()
    assert [k["name"] for k in body["racks"]] == ["C01", "C02", "C03"]
    item = body["racks"][0]["devices"][0]
    for key in ("effective_front_image", "serial_unavailable", "serial_note", "profile_id", "effective_asset_type",
                "needs_review", "needs_review_reason", "connection_count"):
        assert key in item
    assert item["connection_count"] == 1 and item["effective_front_image"]["url"]
    assert body["racks"][0]["u_used"] == 2
    assert client.get("/rows/999999/front").status_code == 404


def _count(client, engine, url):
    seen = []
    fn = lambda *a, **k: seen.append(1)  # noqa: E731
    event.listen(engine, "before_cursor_execute", fn)
    try:
        assert client.get(url).status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", fn)
    return len(seen)


def test_row_front_no_n_plus_one(client, engine):
    row_id, _ = _setup(client, 2)
    small = _count(client, engine, f"/rows/{row_id}/front")
    for i in range(3, 7):
        r = client.post("/racks", json={"row_id": row_id, "name": f"C{i:02d}", "pos_x": i}).json()
        client.post("/devices", json={"host_name": f"x{i}", "device_type_id": dtype(client, 1, name=f"T{i}")["id"],
                                      "rack_id": r["id"], "position_u": 1})
    assert _count(client, engine, f"/rows/{row_id}/front") == small


def test_items_carry_profile_depth_and_mounting(client):
    from tests.test_locations import COMPLETE, publish_profile
    row_id, racks = _setup(client, 1)
    t = dtype(client, 1, name="HalfPanel")
    p = client.post(f"/device-types/{t['id']}/profiles", json={"name": "half"}).json()
    fields = {**COMPLETE, "is_full_depth": False, "depth_mm": 300, "mounting": "rack_19in"}
    publish_profile(client, t["id"], p["id"], fields=fields)
    rid = racks[0]["id"]
    r = client.post("/devices", json={"host_name": "rear-half", "profile_id": p["id"], "rack_id": rid,
                                      "position_u": 20, "face": "rear"})
    assert r.status_code == 201, r.text
    for items in (client.get(f"/racks/{rid}/elevation").json()["devices"],
                  client.get(f"/rows/{row_id}/front").json()["racks"][0]["devices"]):
        d = next(i for i in items if i["host_name"] == "rear-half")
        assert (d["is_full_depth"], d["depth_mm"], d["mounting"], d["face"]) == (False, 300.0, "rack_19in", "rear")
        assert d["manufacturer"] == t["manufacturer"] and d["model"] == "HalfPanel" and "weight_kg" in d
        assert "owner" not in d and "managed_by_group_id" not in d
        full = next(i for i in items if i["host_name"] != "rear-half")
        assert full["is_full_depth"] is True and "depth_mm" in full and "mounting" in full
