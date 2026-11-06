import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

CSV = {"Content-Type": "text/csv"}


def test_serial_unavailable_rules_and_filter(client):
    a = client.post("/devices", json={"host_name": "a", "serial_unavailable": True, "serial_note": "behind PSU"})
    assert a.status_code == 201 and a.json()["serial_note"] == "behind PSU"
    r = client.post("/devices", json={"host_name": "b", "serial_unavailable": True, "serial_number": "S1"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "serial_conflict"
    b = client.post("/devices", json={"host_name": "b", "serial_number": "S1"}).json()
    client.post("/devices", json={"host_name": "c"})
    assert client.patch(f"/devices/{b['id']}", json={"serial_unavailable": True}).status_code == 422
    ok = client.patch(f"/devices/{b['id']}", json={"serial_unavailable": True, "serial_number": None})
    assert ok.status_code == 200 and ok.json()["serial_unavailable"] is True
    client.post("/devices", json={"host_name": "d", "serial_number": "S2"})
    missing = sorted(d["host_name"] for d in client.get("/devices?missing_serial=true").json())
    assert missing == ["a", "b", "c"]
    assert [d["host_name"] for d in client.get("/devices?missing_serial=false").json()] == ["d"]
    assert client.post("/devices", json={"host_name": "e", "serial_note": "x" * 129}).status_code == 422


def test_serial_flags_csv(client):
    body = "host_name,serial_unavailable,serial_note\nx,true,sealed chassis\ny,,\n"
    assert client.post("/devices/import?dry_run=false", content=body, headers=CSV).json()["created"] == 2
    export = client.get("/devices/export").text
    assert "serial_unavailable" in export.splitlines()[0] and "sealed chassis" in export
    bad = "host_name,serial_number,serial_unavailable\nz,S9,true\n"
    assert client.post("/devices/import", content=bad, headers=CSV).json()["errors"]


def test_serial_check_in_db(engine):
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO devices (host_name, serial_number, serial_unavailable) VALUES ('q', 'S', true)"))
