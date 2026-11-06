from tests.test_locations import complete_default, make_rack


def mk(client, mfr, model, u=1, asset=None, complete=True):
    t = client.post("/device-types", json={"manufacturer": mfr, "name": model, "u_height": u,
                                           **({"asset_type": asset} if asset else {})}).json()
    return complete_default(client, t) if complete else t


def test_profiles_catalog(client, client_as):
    a = mk(client, "Dell", "R660", asset="server")
    b = mk(client, "Cisco", "N9K", asset="switch")
    mk(client, "Acme", "Bare", complete=False)
    rack = make_rack(client)
    client.post("/devices", json={"host_name": "x", "rack_id": rack["id"], "position_u": 1, "device_type_id": a["id"]})
    ro = client_as("read-only")
    r = ro.get("/profiles")
    assert r.status_code == 200 and r.headers["X-Total-Count"] == "3"
    items = {i["model"]: i for i in r.json()}
    assert items["R660"]["device_count"] == 1 and items["R660"]["status"] == "published"
    assert items["Bare"]["status"] == "draft" and items["Bare"]["front_image"] is None
    assert items["N9K"]["effective_asset_type"] == "switch" and items["R660"]["manufacturer"] == "Dell"
    assert [i["model"] for i in ro.get("/profiles?status=published").json()] == ["N9K", "R660"]
    assert [i["model"] for i in ro.get("/profiles?q=dell").json()] == ["R660"]
    assert [i["model"] for i in ro.get("/profiles?asset_type=switch").json()] == ["N9K"]
    assert [i["model"] for i in ro.get(f"/profiles?device_type_id={b['id']}").json()] == ["N9K"]
    assert [i["model"] for i in ro.get("/profiles?in_use=true").json()] == ["R660"]
    assert [i["model"] for i in ro.get("/profiles?sort=-device_count,model").json()][0] == "R660"
    assert ro.get("/profiles?sort=secret").status_code == 422
    r = ro.get("/profiles?limit=1&offset=1&sort=model")
    assert [i["model"] for i in r.json()] == ["N9K"] and r.headers["X-Total-Count"] == "3"


def test_profiles_requires_auth(anon):
    assert anon.get("/profiles").status_code == 401


def test_profiles_no_n_plus_one(client, engine):
    from sqlalchemy import event
    for i in range(6):
        mk(client, "M", f"T{i}")
    statements = []

    def count(*a, **k):
        statements.append(1)
    event.listen(engine, "before_cursor_execute", count)
    try:
        assert len(client.get("/profiles").json()) == 6
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert len(statements) <= 9  # auth/session lookups + count + page + images + readiness, independent of row count


def test_asset_type_fixed_list(client):
    r = client.post("/device-types", json={"manufacturer": "X", "name": "Y", "asset_type": "appliance"})
    assert r.status_code == 422
    t = client.post("/device-types", json={"manufacturer": "X", "name": "Y", "asset_type": "patch_panel"}).json()
    assert t["asset_type"] == "patch_panel"
    assert client.get("/profiles?asset_type=bogus").status_code == 422
