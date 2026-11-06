import csv
import io

from tests.test_locations import dtype, make_rack, place

HEADERS = {"Content-Type": "text/csv"}


def test_status_enum_and_search_by_serial(client):
    assert client.post("/devices", json={"host_name": "x", "status": "bogus"}).status_code == 422
    client.post("/devices", json={"host_name": "a", "serial_number": "SN-123"})
    client.post("/devices", json={"host_name": "b"})
    assert [d["host_name"] for d in client.get("/devices", params={"q": "sn-1"}).json()] == ["a"]
    # unique when present; many devices may have none
    r = client.post("/devices", json={"host_name": "c", "serial_number": "SN-123"})
    assert r.status_code == 409 and "serial_number" in r.json()["detail"]
    assert client.post("/devices", json={"host_name": "d"}).status_code == 201
    b = client.get("/devices", params={"q": "b"}).json()[0]
    assert client.patch(f"/devices/{b['id']}", json={"serial_number": "SN-123"}).status_code == 409


def test_device_pagination(client):
    for i in range(7):
        client.post("/devices", json={"host_name": f"h{i}"})
    r = client.get("/devices", params={"limit": 3, "offset": 6})
    assert [d["host_name"] for d in r.json()] == ["h6"] and r.headers["X-Total-Count"] == "7"


def test_export_csv(client):
    rack = make_rack(client)
    dt = dtype(client, 2, name="R750")
    place(client, rack, dt, 3, host="web-01")
    r = client.get("/devices/export")
    assert r.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert rows[0]["host_name"] == "web-01" and rows[0]["model"] == "R750" and rows[0]["position_u"] == "3"


def test_import_dry_run_reports_per_row_errors_and_saves_nothing(client):
    rack = make_rack(client, u_height=10)
    dtype(client, 2, name="R750")
    body = (
        "host_name,status,manufacturer,model,rack_id,position_u,face\n"
        f"ok-1,active,Acme,R750,{rack['id']},1,front\n"
        f"clash,active,Acme,R750,{rack['id']},2,front\n"
        "bad-status,nope,,,,,\n"
        "unknown,active,Foo,Bar,,,\n"
    )
    r = client.post("/devices/import", content=body, headers=HEADERS)
    res = r.json()
    assert r.status_code == 200 and res["dry_run"] is True and res["created"] == 0
    assert [e["row"] for e in res["errors"]] == [3, 4, 5]
    assert "overlaps device 'ok-1'" in res["errors"][0]["errors"][0]
    assert "Unknown device type" in res["errors"][2]["errors"][0]
    assert client.get("/devices").json() == []


def test_import_commits_when_valid(client):
    rack = make_rack(client)
    dtype(client, 1, name="1U")
    body = f"host_name,manufacturer,model,rack_id,position_u\na,Acme,1U,{rack['id']},1\nb,Acme,1U,,\n"
    dry = client.post("/devices/import", content=body, headers=HEADERS).json()
    assert dry["errors"] == [] and dry["created"] == 2
    assert client.get("/devices").json() == []
    r = client.post("/devices/import", params={"dry_run": False}, content=body, headers=HEADERS)
    assert r.json()["created"] == 2
    assert client.get("/devices").headers["X-Total-Count"] == "2"


def test_import_reports_duplicate_serial(client):
    client.post("/devices", json={"host_name": "a", "serial_number": "S1"})
    body = "host_name,serial_number\nb,S2\nc,S1\nd,S2\n"
    res = client.post("/devices/import", content=body, headers=HEADERS).json()
    assert [e["row"] for e in res["errors"]] == [3, 4]
    assert "S1" in res["errors"][0]["errors"][0]


def test_import_requires_header(client):
    r = client.post("/devices/import", content="foo,bar\n1,2\n", headers=HEADERS)
    assert r.status_code == 422


def test_old_status_values_rejected(client):
    for s in ["planned", "maintenance", "decommissioned"]:
        assert client.post("/devices", json={"host_name": s, "status": s}).status_code == 422


def test_all_status_values_accepted(client):
    for s in ["install", "active", "decom"]:
        assert client.post("/devices", json={"host_name": s, "status": s}).status_code == 201
    d = client.get("/devices", params={"status": "active"}).json()[0]
    assert client.patch(f"/devices/{d['id']}", json={"status": "decom"}).json()["status"] == "decom"


def test_unplaced_filter(client):
    rack = make_rack(client)
    place(client, rack, dtype(client, 1), 1, host="racked")
    client.post("/devices", json={"host_name": "loose"})
    assert [d["host_name"] for d in client.get("/devices", params={"unplaced": True}).json()] == ["loose"]
    r = client.get("/devices", params={"unplaced": False})
    assert [d["host_name"] for d in r.json()] == ["racked"] and r.headers["X-Total-Count"] == "1"
    assert len(client.get("/devices").json()) == 2
