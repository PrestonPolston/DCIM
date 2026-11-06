from sqlmodel import Session, select

from app.modules.history.models import DeviceNameHistoryRow


def test_rename_twice_two_rows_and_search_by_old_name(client):
    d = client.post("/devices", json={"host_name": "alpha"}).json()
    client.patch(f"/devices/{d['id']}", json={"host_name": "beta"})
    client.patch(f"/devices/{d['id']}", json={"host_name": "gamma", "notes": "x"})
    client.patch(f"/devices/{d['id']}", json={"notes": "no rename"})
    hist = client.get(f"/devices/{d['id']}/name-history").json()
    assert [(h["old_name"], h["new_name"]) for h in hist] == [("beta", "gamma"), ("alpha", "beta")]
    assert hist[0]["change_set_id"] and hist[0]["changed_by"]
    assert [x["host_name"] for x in client.get("/devices?q=ALPH").json()] == ["gamma"]


def test_failed_rename_rolls_back(client, engine):
    from tests.test_locations import complete_default
    t = complete_default(client, client.post("/device-types", json={"manufacturer": "A", "name": "B"}).json())
    s = client.post("/sites", json={"name": "S"}).json()
    h = client.post("/halls", json={"site_id": s["id"], "name": "H"}).json()
    r = client.post("/rows", json={"hall_id": h["id"], "name": "R"}).json()
    k = client.post("/racks", json={"row_id": r["id"], "name": "K"}).json()
    client.post("/devices", json={"host_name": "one", "rack_id": k["id"], "position_u": 1, "device_type_id": t["id"]})
    two = client.post("/devices", json={"host_name": "two", "rack_id": k["id"], "position_u": 5,
                                        "device_type_id": t["id"]}).json()
    assert client.patch(f"/devices/{two['id']}", json={"host_name": "ONE"}).status_code == 409
    with Session(engine) as s:
        assert s.exec(select(DeviceNameHistoryRow)).all() == []
