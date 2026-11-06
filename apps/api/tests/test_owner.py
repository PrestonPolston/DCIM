import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

CSV = {"Content-Type": "text/csv"}


def test_owner_blank_is_null_and_filter_case_insensitive(client):
    assert client.post("/devices", json={"host_name": "a", "owner": "   "}).json()["owner"] is None
    client.post("/devices", json={"host_name": "b", "owner": "Payments Team"})
    client.post("/devices", json={"host_name": "c", "owner": "Search"})
    names = [d["host_name"] for d in client.get("/devices?owner=payments team").json()]
    assert names == ["b"]


def test_owner_csv_stored_as_text(client):
    r = client.post("/devices/import?dry_run=false", content="host_name,owner\nx,Infra Ops\n", headers=CSV)
    assert r.json()["created"] == 1
    assert client.get("/devices?owner=INFRA OPS").json()[0]["owner"] == "Infra Ops"
    assert "owner" in client.get("/devices/export").text.splitlines()[0]


def test_owner_check(engine):
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO devices (host_name, owner) VALUES ('z', '  ')"))
