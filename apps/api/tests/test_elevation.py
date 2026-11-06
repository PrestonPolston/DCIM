from tests.test_floor_plan import setup_hall
from tests.test_locations import dtype, place


def test_rack_elevation(client):
    _, hall, row = setup_hall(client)
    rack = client.post("/racks", json={"row_id": row["id"], "name": "R1", "u_height": 10}).json()
    half = dtype(client, 1, full_depth=False, name="half")
    two_u = dtype(client, 2, name="2U")
    place(client, rack, two_u, 7, host="top")
    b = place(client, rack, half, 1, face="rear", host="rear-1").json()
    place(client, rack, half, 1, face="front", host="front-1")
    client.patch(f"/devices/{b['id']}", json={"serial_number": "SN1"})
    client.post("/devices", json={"host_name": "unracked"})

    el = client.get(f"/racks/{rack['id']}/elevation").json()
    assert {k: el[k] for k in ("id", "row_id", "name", "u_height")} == {
        "id": rack["id"], "row_id": row["id"], "name": "R1", "u_height": 10}
    assert [d["host_name"] for d in el["devices"]] == ["rear-1", "front-1", "top"]
    top = el["devices"][2]
    assert (top["position_u"], top["top_u"], top["face"], top["status"], top["serial_number"]) == (7, 8, "front", "install", None)
    assert top["device_type"] == {k: two_u[k] for k in top["device_type"]}
    assert el["devices"][0]["serial_number"] == "SN1"
    assert (el["u_used"], el["u_free"]) == (4, 6)

    layout_rack = client.get(f"/halls/{hall['id']}/layout").json()["rows"][0]["racks"][0]
    assert (layout_rack["u_used"], layout_rack["u_free"]) == (el["u_used"], el["u_free"])
    assert client.get("/racks/999/elevation").status_code == 404


def test_empty_rack_elevation(client):
    _, _, row = setup_hall(client)
    rack = client.post("/racks", json={"row_id": row["id"], "name": "R1"}).json()
    el = client.get(f"/racks/{rack['id']}/elevation").json()
    assert (el["devices"], el["u_used"], el["u_free"]) == ([], 0, 53)


def test_racks_filter_by_hall(client):
    site, hall, row = setup_hall(client)
    row2 = client.post("/rows", json={"hall_id": hall["id"], "name": "2"}).json()
    hall_b = client.post("/halls", json={"site_id": site["id"], "name": "B"}).json()
    row_b = client.post("/rows", json={"hall_id": hall_b["id"], "name": "1"}).json()
    for r, n in [(row, "A1"), (row2, "A2"), (row_b, "B1")]:
        client.post("/racks", json={"row_id": r["id"], "name": n})
    r = client.get("/racks", params={"hall_id": hall["id"]})
    assert [x["name"] for x in r.json()] == ["A1", "A2"] and r.headers["X-Total-Count"] == "2"
    assert [x["name"] for x in client.get("/racks", params={"hall_id": hall_b["id"], "q": "b"}).json()] == ["B1"]
