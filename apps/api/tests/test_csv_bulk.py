import time

from sqlmodel import Session, func, select

from app.modules.audit.models import AuditEventRow
from app.modules.devices.models import DeviceRow
from app.modules.history.models import DeviceStatusHistoryRow
from tests.conftest import TEST_DATABASE_URL
from tests.test_locations import dtype, make_rack

CSV = {"Content-Type": "text/csv"}


def test_10k_rows_within_budget_and_complete_history(client, engine, monkeypatch):
    from app.settings import get_settings
    monkeypatch.setattr(get_settings(), "csv_max_bytes", 5_000_000)
    body = "host_name,serial_number\n" + "".join(f"h{i},S{i}\n" for i in range(10_000))
    t = time.time()
    r = client.post("/devices/import?dry_run=false", content=body, headers=CSV)
    elapsed = time.time() - t
    assert r.status_code == 200 and r.json()["created"] == 10_000, r.text[:300]
    assert elapsed < (10 if not TEST_DATABASE_URL else 20), elapsed
    with Session(engine) as s:
        count = lambda m, *w: s.exec(select(func.count()).select_from(m).where(*w)).one()  # noqa: E731
        assert count(DeviceRow) == 10_000 and count(DeviceStatusHistoryRow) == 10_000
        assert count(AuditEventRow, AuditEventRow.action == "device.import") == 10_000


def test_intra_file_conflicts_and_dry_run_writes_nothing(client):
    rack = make_rack(client)
    t = dtype(client, 1, name="1U")
    body = ("host_name,serial_number,device_type_id,rack_id,position_u\n"
            f"a,S1,{t['id']},{rack['id']},1\n"
            f"A,S2,{t['id']},{rack['id']},2\n"      # same host in the same rack (case-insensitive)
            f"b,S3,{t['id']},{rack['id']},1\n"      # same U
            f"c,S1,{t['id']},,\n"                   # duplicate serial in the file
            f"d,S4,{t['id']},,\n")
    r = client.post("/devices/import?dry_run=true", content=body, headers=CSV).json()
    assert [e["row"] for e in r["errors"]] == [3, 4, 5]
    assert [e["details"][0]["code"] for e in r["errors"]][2] == "serial_conflict"
    assert client.get("/devices").json() == []


def test_unknown_headers_are_an_error(client):
    r = client.post("/devices/import", content="host_name,hostnmae\nx,y\n", headers=CSV)
    assert r.status_code == 422 and r.json()["detail"]["columns"] == ["hostnmae"]
