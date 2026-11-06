import pytest
import csv
import io

from sqlalchemy import text

HEADERS = {"Content-Type": "text/csv"}


def test_formula_cells_rejected_per_row_and_nothing_saved(client):
    body = "host_name,serial_number,model\nok-1,S1,\n=cmd|' /C calc'!A0,S2,\nok-2,@SUM(1),\nok-3,S3,+x\n"
    r = client.post("/devices/import?dry_run=false", content=body, headers=HEADERS).json()
    assert [e["row"] for e in r["errors"]] == [3, 4, 5]
    assert "host_name: cell starts with" in r["errors"][0]["errors"][0]
    assert "model:" in r["errors"][2]["errors"][0]
    assert r["created"] == 0 and client.get("/devices").json() == []


def test_formula_rejected_on_json_api_too(client):
    r = client.post("/devices", json={"host_name": "=1+1"})
    assert r.status_code == 422 and "formula" in r.text
    assert client.post("/sites", json={"name": "-x"}).status_code == 422


@pytest.mark.pre_p1_18
def test_export_neutralizes_legacy_formula_values(client, engine):
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO devices(host_name, status, face, serial_number) "
                          "VALUES ('=1+1', 'active', 'front', '@evil')"))
    r = client.get("/devices/export")
    row = next(csv.DictReader(io.StringIO(r.text)))
    assert row["host_name"] == "'=1+1" and row["serial_number"] == "'@evil"
    assert r.headers["Cache-Control"] == "no-store" and r.headers["X-Content-Type-Options"] == "nosniff"
    # reading the legacy device through the API still works
    assert client.get("/devices").json()[0]["host_name"] == "=1+1"


def test_size_limit_413(client):
    big = "host_name\n" + ("x" * 99 + "\n") * 61_000  # ~6 MB
    assert client.post("/devices/import", content=big, headers=HEADERS).status_code == 413


def test_row_limit_and_encoding(client, monkeypatch):
    from app.settings import get_settings

    monkeypatch.setattr(get_settings(), "csv_max_rows", 3)
    r = client.post("/devices/import", content="host_name\na\nb\nc\nd\n", headers=HEADERS)
    assert r.status_code == 422 and "more than 3 rows" in r.text
    assert client.post("/devices/import", content="host_name\n\xff\n".encode("latin-1"), headers=HEADERS).status_code == 422
    assert client.post("/devices/import", content=b"host_name\na\x00b\n", headers=HEADERS).status_code == 422
    bom = "\ufeffhost_name\nbom-ok\n".encode()
    assert client.post("/devices/import", content=bom, headers=HEADERS).json()["errors"] == []


def test_content_type_and_field_size(client):
    assert client.post("/devices/import", content="host_name\na\n",
                       headers={"Content-Type": "text/plain"}).status_code == 415
    huge = "host_name\n" + '"' + "y" * 20_000 + '"\n'
    assert client.post("/devices/import", content=huge, headers=HEADERS).status_code == 422


def test_unknown_columns_rejected(client):  # item 9 (was a warning)
    r = client.post("/devices/import", content="host_name,bogus\na,hello\n", headers=HEADERS)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "unknown_columns"


def test_input_validation(client):
    assert client.post("/devices", json={"host_name": "h" * 254}).status_code == 422
    assert client.post("/devices", json={"host_name": "a", "bogus": 1}).status_code == 422
    assert client.post("/devices", json={"host_name": "a\x07b"}).status_code == 422
    assert client.post("/devices", json={"host_name": "  padded  "}).json()["host_name"] == "padded"
    site = client.post("/sites", json={"name": "S"}).json()
    hall = client.post("/halls", json={"site_id": site["id"], "name": "H"}).json()
    assert client.post("/rows", json={"hall_id": hall["id"], "name": "R", "pos_x": 10_001}).status_code == 422
    assert client.get("/devices", params={"q": "x" * 101}).status_code == 422


def test_search_escapes_wildcards(client):
    client.post("/devices", json={"host_name": "web_01"})
    client.post("/devices", json={"host_name": "webX01"})
    client.post("/devices", json={"host_name": "100%-cpu"})
    assert [d["host_name"] for d in client.get("/devices", params={"q": "_"}).json()] == ["web_01"]
    assert [d["host_name"] for d in client.get("/devices", params={"q": "%"}).json()] == ["100%-cpu"]
