import csv
import io

from tests.test_locations import dtype


def build(client):
    site = client.post("/sites", json={"name": "DAL1"}).json()
    hall = client.post("/halls", json={"site_id": site["id"], "name": "H1"}).json()
    hall2 = client.post("/halls", json={"site_id": site["id"], "name": "H2"}).json()
    r1 = client.post("/rows", json={"hall_id": hall["id"], "name": "A"}).json()
    r2 = client.post("/rows", json={"hall_id": hall2["id"], "name": "B"}).json()
    k1 = client.post("/racks", json={"row_id": r1["id"], "name": "A-01"}).json()
    k2 = client.post("/racks", json={"row_id": r1["id"], "name": "A-02"}).json()
    k3 = client.post("/racks", json={"row_id": r2["id"], "name": "B-01"}).json()
    t = dtype(client, 1)["id"]
    for host, rack, u, status in [("web-1", k1, 1, "active"), ("web-2", k1, 2, "install"),
                                  ("db-1", k2, 1, "active"), ("far-1", k3, 1, "install")]:
        client.post("/devices", json={"host_name": host, "rack_id": rack["id"], "position_u": u,
                                      "device_type_id": t, "status": status})
    client.post("/devices", json={"host_name": "loose", "status": "decom"})
    return hall, hall2, r1, k1, k2


def names(r):
    return [d["host_name"] for d in r.json()]


def test_location_multi_value_filters_and_sort(client):
    hall, hall2, r1, k1, k2 = build(client)
    assert sorted(names(client.get(f"/devices?hall_id={hall['id']}"))) == ["db-1", "web-1", "web-2"]
    assert names(client.get(f"/devices?room_id={hall2['id']}")) == ["far-1"]
    assert sorted(names(client.get(f"/devices?row_id={r1['id']}"))) == ["db-1", "web-1", "web-2"]
    r = client.get(f"/devices?rack_id={k1['id']}&rack_id={k2['id']}&sort=-host_name")
    assert names(r) == ["web-2", "web-1", "db-1"] and r.headers["X-Total-Count"] == "3"
    r = client.get("/devices?status=install&status=decom&sort=status,host_name")
    assert names(r) == ["loose", "far-1", "web-2"]
    assert client.get("/devices?sort=password").status_code == 422
    assert client.get("/devices?status=bogus").status_code == 422
    assert names(client.get("/devices?sort=-position_u,host_name&limit=2")) and \
        client.get("/devices?sort=-position_u&limit=2").headers["X-Total-Count"] == "5"


def test_export_has_locations_and_same_filters(client):
    hall, *_ = build(client)
    text = client.get(f"/devices/export?hall_id={hall['id']}&status=active&sort=host_name").text
    rows = list(csv.DictReader(io.StringIO(text)))
    assert [r["host_name"] for r in rows] == ["db-1", "web-1"]
    assert (rows[0]["site"], rows[0]["hall"], rows[0]["row"], rows[0]["cabinet"]) == ("DAL1", "H1", "A", "A-02")
    assert "serial_unavailable" in rows[0] and "serial_note" in rows[0]
