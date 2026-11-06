import csv
import io

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app.modules.connections.models import ConnectionRow, DevicePortRow
from tests.test_locations import dtype, make_rack


@pytest.fixture
def world(client):
    rack = make_rack(client)
    t = dtype(client, 1)
    sw = client.post("/devices", json={"host_name": "sw-1", "rack_id": rack["id"], "position_u": 40,
                                       "device_type_id": t["id"], "status": "active"}).json()
    srv = client.post("/devices", json={"host_name": "srv-1", "rack_id": rack["id"], "position_u": 10,
                                        "device_type_id": t["id"], "status": "install"}).json()
    loose = client.post("/devices", json={"host_name": "loose", "status": "active"}).json()
    return {"rack": rack, "sw": sw, "srv": srv, "loose": loose}


def connect(client, a, ap, b, bp, **kw):
    return client.post("/connections", json={"a_device_id": a["id"], "a_port_name": ap,
                                             "b_device_id": b["id"], "b_port_name": bp, **kw})


def test_ports_crud_and_name_conflict(client, world):
    r = client.post(f"/devices/{world['sw']['id']}/ports", json={"name": "Gi1/0/1", "kind": "ethernet",
                                                                  "speed_mbps": 1000})
    assert r.status_code == 201 and r.json()["role"] == "endpoint" and r.json()["connection_id"] is None
    r = client.post(f"/devices/{world['sw']['id']}/ports", json={"name": "gi1/0/1"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "port_name_conflict"
    assert client.post(f"/devices/{world['sw']['id']}/ports", json={"name": "x", "kind": "bogus"}).status_code == 422
    assert client.post("/devices/9999/ports", json={"name": "x"}).status_code == 404
    assert len(client.get(f"/devices/{world['sw']['id']}/ports").json()) == 1


def test_create_connection_autocreates_ports_and_shapes(client, world):
    r = connect(client, world["srv"], "eth0", world["sw"], "Gi1/0/12", cable_type="RJ45", cable_label="C-0001",
                cable_color="blue", cable_length_m="2.5", notes="uplink")
    assert r.status_code == 201, r.text
    c = r.json()
    assert {c["a"]["host_name"], c["b"]["host_name"]} == {"srv-1", "sw-1"}
    assert c["a"]["port_id"] < c["b"]["port_id"]  # a/b = canonical port1/port2
    assert c["cable"]["label"] == "C-0001" and c["cable"]["cable_type"] == "RJ45"
    assert c["derived_status"] == "install"  # srv-1 is install
    assert c["a"]["cabinet"] == "R01" and c["a"]["hall"] == "Hall A" and c["a"]["row"] == "Row 1"
    ports = client.get(f"/devices/{world['srv']['id']}/ports").json()
    assert ports[0]["name"] == "eth0" and ports[0]["connection_id"] == c["id"]

    dc = client.get(f"/devices/{world['srv']['id']}/connections").json()
    assert len(dc) == 1 and dc[0]["local_port"]["name"] == "eth0" and dc[0]["far_port"]["name"] == "Gi1/0/12"
    assert dc[0]["far_device"]["host_name"] == "sw-1" and dc[0]["far_device"]["position_u"] == 40
    assert (dc[0]["local_status"], dc[0]["far_status"], dc[0]["derived_status"]) == ("install", "active", "install")
    assert client.get(f"/devices/{world['sw']['id']}/connections").json()[0]["local_port"]["name"] == "Gi1/0/12"


def test_one_connection_per_port_and_no_self(client, world):
    assert connect(client, world["srv"], "eth0", world["sw"], "p1").status_code == 201
    for a, ap, b, bp in [(world["srv"], "ETH0", world["loose"], "p1"), (world["loose"], "p1", world["sw"], "p1")]:
        r = connect(client, a, ap, b, bp)
        assert r.status_code == 409 and r.json()["detail"]["code"] == "port_in_use", r.text
    r = connect(client, world["loose"], "p1", world["loose"], "p1")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "self_connection"
    # two ports on the same device is fine (loopback cable)
    assert connect(client, world["loose"], "p1", world["loose"], "p2").status_code == 201
    r = client.post("/connections", json={"a_device_id": 9999, "a_port_name": "x",
                                          "b_device_id": world["sw"]["id"], "b_port_name": "y"})
    assert r.status_code == 404
    r = client.post("/connections", json={"a_device_id": world["sw"]["id"], "b_device_id": world["srv"]["id"],
                                          "b_port_name": "y"})
    assert r.status_code == 422
    assert connect(client, world["srv"], "e9", world["sw"], "p9", cable_type="CAT9").status_code == 422


def test_db_enforces_occupancy(engine, client, world):
    connect(client, world["srv"], "a", world["sw"], "b")
    with Session(engine) as s:
        p = DevicePortRow(device_id=world["loose"]["id"], name="z")
        s.add(p)
        s.flush()
        a = s.exec(__import__("sqlmodel").select(DevicePortRow).where(DevicePortRow.name == "a")).one()
        s.add(ConnectionRow(port1_id=min(a.id, p.id), port2_id=max(a.id, p.id)))
        with pytest.raises(IntegrityError):  # same port in the same column twice
            s.flush()
        s.rollback()
        s.add(ConnectionRow(port1_id=p.id, port2_id=p.id))
        with pytest.raises(IntegrityError):
            s.flush()


def test_patch_and_delete_frees_port_and_label(client, world):
    c = connect(client, world["srv"], "eth0", world["sw"], "p1", cable_label="L1").json()
    r = client.patch(f"/connections/{c['id']}", json={"cable_type": "LC", "cable_color": "aqua", "notes": "n"})
    assert r.status_code == 200 and r.json()["cable"]["cable_type"] == "LC" and r.json()["notes"] == "n"
    other = connect(client, world["loose"], "q1", world["loose"], "q2").json()
    r = client.patch(f"/connections/{other['id']}", json={"cable_label": "l1"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "cable_label_conflict"
    assert client.patch(f"/connections/{c['id']}", json={"a_device_id": 1}).status_code == 422
    assert client.delete(f"/connections/{c['id']}").status_code == 204
    assert client.get(f"/connections/{c['id']}").status_code == 404
    assert client.delete(f"/connections/{c['id']}").status_code == 404
    # port and label are free again
    assert connect(client, world["srv"], "eth0", world["loose"], "q3", cable_label="L1").status_code == 201


def test_decom_keeps_connections_derived_decom(client, world):
    c = connect(client, world["srv"], "eth0", world["sw"], "p1").json()
    client.patch(f"/devices/{world['sw']['id']}", json={"status": "active"})
    assert client.patch(f"/devices/{world['srv']['id']}", json={"status": "decom"}).status_code == 200
    got = client.get(f"/connections/{c['id']}").json()
    assert got["derived_status"] == "decom"
    end = got["a"] if got["a"]["host_name"] == "srv-1" else got["b"]
    assert end["status"] == "decom" and end["rack_id"] is None  # decom unracks, connection stays


def test_list_filters_and_export(client, world):
    c1 = connect(client, world["srv"], "eth0", world["sw"], "p1", cable_type="RJ45", cable_label="C1").json()
    assert connect(client, world["srv"], "e5", world["sw"], "p5", cable_label="=HACK()").status_code == 422
    r2 = connect(client, world["loose"], "e1", world["sw"], "p2", cable_type="DAC")
    assert r2.status_code == 201, r2.text
    r3 = connect(client, world["loose"], "e2", world["loose"], "e3", cable_type="LC")
    assert r3.status_code == 201, r3.text
    r = client.get("/connections")
    assert r.headers["X-Total-Count"] == "3"
    rack = world["rack"]["id"]
    assert client.get(f"/connections?rack_id={rack}").headers["X-Total-Count"] == "2"
    assert client.get(f"/connections?device_id={world['loose']['id']}").headers["X-Total-Count"] == "2"
    assert [x["id"] for x in client.get("/connections?cable_type=RJ45").json()] == [c1["id"]]
    assert client.get("/connections?cable_type=RJ45&cable_type=LC").headers["X-Total-Count"] == "2"
    assert client.get("/connections?q=eth0").headers["X-Total-Count"] == "1"
    assert client.get("/connections?derived_status=install").headers["X-Total-Count"] == "1"
    assert client.get("/connections?derived_status=active").headers["X-Total-Count"] == "2"
    assert client.get("/connections?cross_cabinet=true").headers["X-Total-Count"] == "2"
    hall = client.get("/halls").json()[0]["id"]
    assert client.get(f"/connections?room_id={hall}").headers["X-Total-Count"] == "2"
    assert client.get("/connections?cable_type=CAT9").status_code == 422
    assert client.get("/connections?limit=1").headers["X-Total-Count"] == "3"

    text = client.get(f"/connections/export?rack_id={rack}").text
    rows = list(csv.DictReader(io.StringIO(text)))
    assert len(rows) == 2
    first = next(x for x in rows if x["id"] == str(c1["id"]))
    assert {first["a_status"], first["b_status"]} == {"install", "active"} and first["derived_status"] == "install"
    assert first["cable_label"] == "C1"
    assert first["a_cabinet"] == "R01" and first["a_hall"] == "Hall A"


def test_rbac(client_as, world):
    ro = client_as("read-only")
    tech = client_as("technician")
    assert ro.get("/connections").status_code == 200
    assert ro.get("/connections/export").status_code == 200
    assert ro.get(f"/devices/{world['sw']['id']}/ports").status_code == 200
    assert ro.get(f"/devices/{world['sw']['id']}/connections").status_code == 200
    assert ro.post(f"/devices/{world['sw']['id']}/ports", json={"name": "x"}).status_code == 403
    assert connect(ro, world["srv"], "a", world["sw"], "b").status_code == 403
    r = connect(tech, world["srv"], "a", world["sw"], "b")
    assert r.status_code == 201
    cid = r.json()["id"]
    assert ro.patch(f"/connections/{cid}", json={"notes": "x"}).status_code == 403
    assert ro.delete(f"/connections/{cid}").status_code == 403
    assert tech.patch(f"/connections/{cid}", json={"notes": "x"}).status_code == 200
    assert tech.delete(f"/connections/{cid}").status_code == 204


def test_audit_events(client, world):
    c = connect(client, world["srv"], "eth0", world["sw"], "p1").json()
    client.delete(f"/connections/{c['id']}")
    actions = [e["action"] for e in client.get("/audit-events?limit=500").json()]
    assert "connection.create" in actions and "connection.delete" in actions and "connection.port.create" in actions


def test_cable_type_check_and_label_ci(engine, client, world):
    from app.modules.connections.models import CableRow
    with Session(engine) as s:
        s.add(CableRow(cable_type="CAT9"))
        with pytest.raises(IntegrityError):
            s.flush()
    assert connect(client, world["srv"], "a", world["sw"], "b", cable_label="X-1").status_code == 201
    r = connect(client, world["srv"], "c", world["sw"], "d", cable_label="x-1")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "cable_label_conflict"


def test_lane_and_panel_columns_exist_unused(engine, client, world):
    c = connect(client, world["srv"], "a", world["sw"], "b").json()
    with Session(engine) as s:
        row = s.get(ConnectionRow, c["id"])
        assert (row.port1_lane, row.port2_lane) == (0, 0)
        port = s.get(DevicePortRow, c["a"]["port_id"])
        assert port.rear_port_id is None and port.lanes is None and port.role == "endpoint"


def test_hard_delete_with_connections_409(client, world, monkeypatch):
    from app.settings import get_settings
    monkeypatch.setattr(get_settings(), "hard_delete_enabled", True)
    c = connect(client, world["srv"], "a", world["sw"], "b").json()
    r = client.delete(f"/devices/{world['srv']['id']}?hard=true")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "device_has_connections"
    assert client.get(f"/devices/{world['srv']['id']}").status_code == 200
    client.delete(f"/connections/{c['id']}")
    assert client.delete(f"/devices/{world['srv']['id']}?hard=true").status_code == 204
