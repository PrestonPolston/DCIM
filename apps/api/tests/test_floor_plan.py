from tests.test_locations import dtype, place


def setup_hall(client):
    site = client.post("/sites", json={"name": "DC1"}).json()
    hall = client.post("/halls", json={"site_id": site["id"], "name": "A"}).json()
    row = client.post("/rows", json={"hall_id": hall["id"], "name": "1", "pos_x": 0, "pos_y": 2, "orientation": "N"}).json()
    return site, hall, row


def test_positions_saved_and_validated(client):
    _, hall, row = setup_hall(client)
    assert (row["pos_x"], row["pos_y"], row["orientation"]) == (0, 2, "N")
    rack = client.post("/racks", json={"row_id": row["id"], "name": "R1"}).json()
    assert (rack["pos_x"], rack["pos_y"], rack["orientation"]) == (None, None, None)
    r = client.patch(f"/racks/{rack['id']}", json={"pos_x": 3, "pos_y": 2, "orientation": "S"})
    assert r.json()["orientation"] == "S"
    assert client.post("/racks", json={"row_id": row["id"], "name": "R2", "orientation": "X"}).status_code == 422
    assert client.post("/racks", json={"row_id": row["id"], "name": "R2", "pos_x": -1}).status_code == 422


def test_racks_cannot_share_floor_cell_in_same_hall(client):
    site, hall, row = setup_hall(client)
    row2 = client.post("/rows", json={"hall_id": hall["id"], "name": "2"}).json()
    client.post("/racks", json={"row_id": row["id"], "name": "R1", "pos_x": 1, "pos_y": 1})
    r = client.post("/racks", json={"row_id": row2["id"], "name": "R2", "pos_x": 1, "pos_y": 1})
    assert r.status_code == 409 and "taken by cabinet 'R1'" in r.json()["detail"]
    r2 = client.post("/racks", json={"row_id": row2["id"], "name": "R2", "pos_x": 2, "pos_y": 1}).json()
    assert client.patch(f"/racks/{r2['id']}", json={"pos_x": 1}).status_code == 409
    assert client.get(f"/racks/{r2['id']}").json()["pos_x"] == 2
    assert client.patch(f"/racks/{r2['id']}", json={"name": "R2b"}).status_code == 200  # same spot as itself ok
    # another hall may reuse the coordinates
    hall_b = client.post("/halls", json={"site_id": site["id"], "name": "B"}).json()
    row_b = client.post("/rows", json={"hall_id": hall_b["id"], "name": "1"}).json()
    assert client.post("/racks", json={"row_id": row_b["id"], "name": "R1", "pos_x": 1, "pos_y": 1}).status_code == 201


def test_hall_layout(client):
    _, hall, row = setup_hall(client)
    empty_row = client.post("/rows", json={"hall_id": hall["id"], "name": "2"}).json()
    rack = client.post("/racks", json={"row_id": row["id"], "name": "R1", "u_height": 10, "pos_x": 0, "pos_y": 2}).json()
    client.post("/racks", json={"row_id": row["id"], "name": "R2"})
    place(client, rack, dtype(client, 2), 1, host="a")
    place(client, rack, dtype(client, 1, name="1U"), 5, host="b")

    layout = client.get(f"/halls/{hall['id']}/layout").json()
    assert layout["id"] == hall["id"] and layout["name"] == "A"
    assert [r["name"] for r in layout["rows"]] == ["1", "2"]
    assert layout["rows"][1] == {**empty_row, "racks": []}
    r1, r2 = layout["rows"][0]["racks"]
    assert (r1["pos_x"], r1["pos_y"], r1["device_count"], r1["u_used"], r1["u_free"]) == (0, 2, 2, 3, 7)
    assert (r2["device_count"], r2["u_used"], r2["u_free"]) == (0, 0, 53)
    assert client.get("/halls/999/layout").status_code == 404


def test_effective_orientation_inherits_row(client):
    _, hall, row = setup_hall(client)  # row faces N
    own = client.post("/racks", json={"row_id": row["id"], "name": "R1", "orientation": "S"}).json()
    inherit = client.post("/racks", json={"row_id": row["id"], "name": "R2"}).json()
    assert (own["orientation"], own["effective_orientation"]) == ("S", "S")
    assert (inherit["orientation"], inherit["effective_orientation"]) == (None, "N")
    assert client.get(f"/racks/{inherit['id']}").json()["effective_orientation"] == "N"
    assert [r["effective_orientation"] for r in client.get("/racks").json()] == ["S", "N"]
    layout = client.get(f"/halls/{hall['id']}/layout").json()
    assert [r["effective_orientation"] for r in layout["rows"][0]["racks"]] == ["S", "N"]
    el = client.get(f"/racks/{inherit['id']}/elevation").json()
    assert (el["orientation"], el["effective_orientation"]) == (None, "N")
    client.patch(f"/rows/{row['id']}", json={"orientation": "E"})
    assert client.get(f"/racks/{inherit['id']}").json()["effective_orientation"] == "E"
    patched = client.patch(f"/racks/{inherit['id']}", json={"orientation": "W"}).json()
    assert patched["effective_orientation"] == "W"


def test_hall_aisle_hints_and_layout_effective_orientation(client):
    h = client.post("/halls", json={"name": "HX", "aisle_axis": "y", "odd_side": "low"}).json()
    assert (h["aisle_axis"], h["odd_side"]) == ("y", "low")
    assert client.post("/halls", json={"name": "HY", "aisle_axis": "z"}).status_code == 422
    row = client.post("/rows", json={"hall_id": h["id"], "name": "R1", "orientation": "E"}).json()
    client.post("/racks", json={"row_id": row["id"], "name": "C1", "pos_x": 0, "pos_y": 0})
    lay = client.get(f"/halls/{h['id']}/layout").json()
    assert lay["aisle_axis"] == "y" and lay["rows"][0]["racks"][0]["effective_orientation"] == "E"
