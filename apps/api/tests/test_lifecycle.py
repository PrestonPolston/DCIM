import pytest
from sqlmodel import Session, select

from app.modules.history.models import ChangeSetRow, DevicePlacementHistoryRow, DeviceStatusHistoryRow
from tests.test_locations import dtype, make_rack, place


@pytest.fixture
def db(client):
    from app.db import get_session
    from app.main import app

    gen = app.dependency_overrides[get_session]()
    session = next(gen)
    yield session
    session.close()


def history(db: Session, model, device_id):
    db.expire_all()
    return db.exec(select(model).where(model.device_id == device_id).order_by(model.id)).all()


def test_decom_auto_unracks_and_frees_u(client, db):
    rack = make_rack(client, u_height=10)
    dt = dtype(client, 2)
    d = place(client, rack, dt, 3, face="rear", host="old").json()
    r = client.patch(f"/devices/{d['id']}", json={"status": "decom"})
    body = r.json()
    assert r.status_code == 200
    assert (body["status"], body["rack_id"], body["position_u"], body["face"]) == ("decom", None, None, "front")
    assert place(client, rack, dt, 3, host="new").status_code == 201  # U is free again
    status_rows = history(db, DeviceStatusHistoryRow, d["id"])
    place_rows = history(db, DevicePlacementHistoryRow, d["id"])
    assert [(s.from_status, s.to_status) for s in status_rows] == [(None, "install"), ("install", "decom")]
    assert [(p.from_rack_id, p.from_position_u, p.from_face, p.to_rack_id) for p in place_rows][-1] == (rack["id"], 3, "rear", None)
    assert status_rows[-1].change_set_id == place_rows[-1].change_set_id


def test_lifecycle_rules(client):
    d = client.post("/devices", json={"host_name": "x", "status": "install"}).json()
    assert client.patch(f"/devices/{d['id']}", json={"status": "active"}).status_code == 200
    assert client.patch(f"/devices/{d['id']}", json={"status": "install"}).status_code == 422
    assert client.patch(f"/devices/{d['id']}", json={"status": "decom"}).status_code == 200
    r = client.patch(f"/devices/{d['id']}", json={"status": "active"})
    assert r.status_code == 422 and "recommission" in r.json()["detail"]
    r = client.patch(f"/devices/{d['id']}", json={"status": "active", "recommission": True})
    assert r.status_code == 200 and r.json()["status"] == "active"


def test_decom_with_placement_rejected(client):
    rack = make_rack(client)
    dt = dtype(client, 1)
    d = place(client, rack, dt, 1).json()
    r = client.patch(f"/devices/{d['id']}", json={"status": "decom", "position_u": 5})
    assert r.status_code == 422
    assert client.post("/devices", json={"host_name": "z", "status": "decom", "rack_id": rack["id"],
                                         "device_type_id": dt["id"], "position_u": 9}).status_code == 422


def test_rack_delete_decoms_devices_and_soft_deletes(client, db):
    rack = make_rack(client, u_height=10)
    dt = dtype(client, 1)
    ids = [place(client, rack, dt, u, host=f"h{u}").json()["id"] for u in (1, 2, 3)]
    r = client.delete(f"/racks/{rack['id']}")
    assert r.status_code == 204 and r.headers["X-Decommissioned-Count"] == "3"
    assert client.get(f"/racks/{rack['id']}").status_code == 404
    assert client.get("/racks").json() == []
    for i in ids:
        d = client.get(f"/devices/{i}").json()
        assert (d["status"], d["rack_id"]) == ("decom", None)
    # one change set covers all devices
    cs = {h.change_set_id for i in ids for h in history(db, DevicePlacementHistoryRow, i)[-1:]}
    assert len(cs) == 1 and db.get(ChangeSetRow, cs.pop()).note.startswith("delete rack")
    # name is reusable; placing into the deleted rack fails
    assert client.post("/racks", json={"row_id": rack["row_id"], "name": rack["name"]}).status_code == 201
    assert client.post("/devices", json={"host_name": "n", "rack_id": rack["id"], "device_type_id": dt["id"],
                                         "position_u": 1}).status_code == 404
    # its row can't be physically deleted while history references the rack
    assert client.delete(f"/rows/{rack['row_id']}").status_code == 409


def test_hostname_reusable_after_decom_and_recommission_clash(client):
    rack = make_rack(client)
    dt = dtype(client, 1)
    old = place(client, rack, dt, 1, host="web01").json()
    client.patch(f"/devices/{old['id']}", json={"status": "decom"})
    assert place(client, rack, dt, 2, host="WEB01").status_code == 201
    r = client.patch(f"/devices/{old['id']}", json={
        "status": "install", "recommission": True, "rack_id": rack["id"], "position_u": 5})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "hostname_conflict" and "already exists in cabinet" in r.json()["detail"]["message"]


def test_soft_delete_device(client):
    rack = make_rack(client)
    dt = dtype(client, 1)
    d = place(client, rack, dt, 1).json()
    assert client.delete(f"/devices/{d['id']}").status_code == 204
    assert client.get(f"/devices/{d['id']}").status_code == 404
    assert client.get("/devices").json() == []
    assert place(client, rack, dt, 1).status_code == 201  # U freed


def test_hard_delete_disabled_by_default(client):
    d = place(client, make_rack(client), dtype(client, 1), 1).json()
    assert client.delete(f"/devices/{d['id']}?hard=true").status_code == 403
    assert client.get(f"/devices/{d['id']}").status_code == 200


def test_hard_delete_admin_only_with_audit_snapshot(client, client_as, db, monkeypatch):
    from app.settings import get_settings
    monkeypatch.setattr(get_settings(), "hard_delete_enabled", True)
    from app.modules.audit.models import AuditEventRow

    rack = make_rack(client)
    d = place(client, rack, dtype(client, 1), 1, host="gone").json()
    tech = client_as("technician")
    assert tech.delete(f"/devices/{d['id']}?hard=true").status_code == 403
    assert client.delete(f"/devices/{d['id']}?hard=true").status_code == 204
    db.expire_all()
    from app.modules.devices.models import DeviceRow
    assert db.get(DeviceRow, d["id"]) is None
    assert history(db, DeviceStatusHistoryRow, d["id"]) == []
    event = db.exec(select(AuditEventRow).where(AuditEventRow.action == "device.hard_delete")).one()
    assert '"host_name": "gone"' in event.before_json and "status_history" in event.before_json
    assert event.retention_class == "restorable" and event.via == "api"
