from tests.test_locations import complete_default
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.test_lifecycle import dtype, make_rack  # noqa: F401

CSV = {"Content-Type": "text/csv"}


def test_create_with_only_host_name(client):
    r = client.post("/devices", json={"host_name": "solo"})
    assert r.status_code == 201
    body = r.json()
    assert body["created_by"] and body["description"] is None and body["asset_type"] is None and body["effective_asset_type"] == "other"  # inherited from the test shim type


def test_descriptive_fields_and_effective_defaults(client):
    t = client.post("/device-types", json={"manufacturer": "Dell", "name": "R1"}).json()
    client.patch(f"/device-types/{t['id']}", json={"asset_type": "server", "eos_date": "2030-01-31"})
    complete_default(client, t)
    d = client.post("/devices", json={
        "host_name": "a", "device_type_id": t["id"], "description": "web", "notes": "n",
        "system_type": "linux", "system_type_confidence": "high", "color_hex": "#A1B2C3",
        "power_assignment": "PDU-A 12", "historic_name": "old-a", "app_service": "shop",
    }).json()
    assert d["effective_asset_type"] == "server" and d["effective_eos_date"] == "2030-01-31"
    assert d["effective_color_hex"] == "#A1B2C3"
    d2 = client.patch(f"/devices/{d['id']}", json={"asset_type": "firewall", "eos_date": "2028-05-01"}).json()
    assert d2["effective_asset_type"] == "firewall" and d2["effective_eos_date"] == "2028-05-01"
    assert client.post("/devices", json={"host_name": "b", "color_hex": "red"}).status_code == 422
    assert client.post("/devices", json={"host_name": "b", "system_type_confidence": "sure"}).status_code == 422
    assert client.post("/devices", json={"host_name": "b", "created_by": "me"}).status_code == 422


@pytest.mark.parametrize("col,bad", [("system_type_confidence", "'sure'"), ("color_hex", "'red'")])
@pytest.mark.pre_p1_18
def test_checks_reject_bad_raw_insert_accept_null(engine, col, bad):
    with engine.begin() as conn:
        conn.execute(text(f"INSERT INTO devices (host_name, {col}) VALUES ('ok', NULL)"))
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text(f"INSERT INTO devices (host_name, {col}) VALUES ('bad', {bad})"))


def test_csv_round_trip_and_asset_tag_alias(client):
    body = "host_name,asset_tag,description,eos_date,system_type_confidence\nx1,AT-1,hello,2031-02-03,low\n"
    r = client.post("/devices/import?dry_run=false", content=body, headers=CSV)
    assert r.json()["created"] == 1, r.json()
    d = client.get("/devices").json()[0]
    assert d["serial_number"] == "AT-1" and d["eos_date"] == "2031-02-03"
    export = client.get("/devices/export").text
    assert "description" in export.splitlines()[0] and "AT-1" in export and "hello" in export
    bad = "host_name,asset_tag,serial_number\nx2,A,B\n"
    r = client.post("/devices/import?dry_run=true", content=bad, headers=CSV).json()
    assert r["errors"] and "asset_tag" in r["errors"][0]["errors"][0]
    same = "host_name,asset_tag,serial_number\nx3,S9,S9\n"
    assert client.post("/devices/import?dry_run=true", content=same, headers=CSV).json()["errors"] == []
