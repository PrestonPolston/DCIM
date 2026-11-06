"""Cross-cabinet move via PATCH /devices/{id}: atomic, fit-checked, one 'moved' history row + one audit event."""
from sqlmodel import Session, select

from app.modules.audit.models import AuditEventRow
from app.modules.history.models import DevicePlacementHistoryRow
from tests.test_locations import dtype, make_rack


def test_cross_cabinet_move_is_atomic_and_recorded(client, engine):
    k1 = make_rack(client)
    row_id = k1["row_id"]
    k2 = client.post("/racks", json={"row_id": row_id, "name": "R02"}).json()
    t = dtype(client, 2)
    d = client.post("/devices", json={"host_name": "mv", "rack_id": k1["id"], "position_u": 1,
                                      "device_type_id": t["id"]}).json()
    client.post("/devices", json={"host_name": "blocker", "rack_id": k2["id"], "position_u": 11,
                                  "device_type_id": t["id"]})
    with Session(engine) as s:
        n_hist = len(s.exec(select(DevicePlacementHistoryRow).where(DevicePlacementHistoryRow.device_id == d["id"])).all())
    # conflicting move: nothing changes
    r = client.patch(f"/devices/{d['id']}", json={"rack_id": k2["id"], "position_u": 10, "face": "rear"})
    assert r.status_code == 409
    assert client.get(f"/devices/{d['id']}").json()["rack_id"] == k1["id"]
    # good move
    r = client.patch(f"/devices/{d['id']}", json={"rack_id": k2["id"], "position_u": 20, "face": "rear"})
    assert r.status_code == 200 and (r.json()["rack_id"], r.json()["position_u"]) == (k2["id"], 20)
    with Session(engine) as s:
        hist = s.exec(select(DevicePlacementHistoryRow).where(DevicePlacementHistoryRow.device_id == d["id"])
                      .order_by(DevicePlacementHistoryRow.id)).all()
        assert len(hist) == n_hist + 1
        h = hist[-1]
        assert (h.from_rack_id, h.to_rack_id) == (k1["id"], k2["id"])
        moves = s.exec(select(AuditEventRow).where(AuditEventRow.action == "device.move",
                                                   AuditEventRow.entity_id == d["id"])).all()
        assert len(moves) == 1
