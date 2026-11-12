"""Job intake v1, slice 2: ePIF CSV staging/preview, commit (per import + whole job), conflict rows skipped with
reasons, PSU fill-later items, epif_not_uploaded auto-resolve, open-item actions, roles."""
from sqlmodel import Session, func, select

from app.modules.audit.models import AuditEventRow
from app.modules.devices.models import DeviceRow
from app.modules.directory.models import ProjectRow
from app.modules.jobs.models import EpifPsuRow, EpifRequestRow, ImportRowRow, JobImportRow, JobOpenItemRow
from tests.test_locations import dtype, make_rack

CSV = {"Content-Type": "text/csv"}
HEAD = "ID,Action,Name,Manufacturer,Model,Template,Managed By,App Service,Row,Rack,RU,Airflow,AC/DC,PSU1,PSU2,S/N"


def _job(client, dcreq="DCREQ0001234"):
    r = client.post("/jobs", json={"dcreq": dcreq})
    assert r.status_code == 201, r.text
    return r.json()


def _env(client):
    rack = make_rack(client)  # DC1 / Hall A / Row 1 / R01, 53U
    t = dtype(client, 1, name="1U")  # Acme 1U, usable published default profile
    return rack, t


def row(i, name, ru, serial=None, rack="R01", row_="Row 1", model="1U", action="Install", psu1="A12", psu2="B12",
        acdc="AC"):
    return ",".join([str(i), action, name, "Acme", model, "", "", "", row_, rack, str(ru) if ru else "", "", acdc,
                     psu1, psu2, serial or ""])


def body(*rows, head=HEAD):
    return head + "\n" + "\n".join(rows) + "\n"


def upload(client, job_id, text, filename="epif.csv", **params):
    return client.post(f"/jobs/{job_id}/imports", params={"filename": filename, **params}, content=text, headers=CSV)


def count(engine, model, *where):
    with Session(engine) as s:
        return s.exec(select(func.count()).select_from(model).where(*where)).one()


# ---- headers ----
def test_forbidden_columns_reject_file_and_stage_nothing(client, engine):
    j = _job(client)
    for head in (HEAD + ",iLO Password", HEAD + ",iDRAC IP", HEAD + ",Secret"):
        r = upload(client, j["id"], body(row(10001, "h1", 1) + ",x", head=head))
        assert r.status_code == 422, r.text
        d = r.json()["detail"]
        assert d["code"] == "import_forbidden_columns" and len(d["headers"]) == 1
        assert "x" not in r.text.split("headers")[1]  # names only, never values
    assert count(engine, JobImportRow) == 0 and count(engine, ImportRowRow) == 0


def test_unknown_duplicate_and_missing_columns(client):
    j = _job(client)
    r = upload(client, j["id"], "Name,Colour\nh1,red\n")
    assert r.status_code == 422 and r.json()["detail"] == {
        "code": "unknown_columns", "message": "Unknown columns: Colour", "columns": ["Colour"]}
    r = upload(client, j["id"], "Name,Hostname\nh1,h2\n")
    assert r.json()["detail"]["code"] == "duplicate_columns"
    r = upload(client, j["id"], "RU\n1\n")
    assert r.json()["detail"]["code"] == "missing_columns"
    assert upload(client, j["id"], "Name\n").json()["detail"]["code"] == "import_empty"
    r = client.post(f"/jobs/{j['id']}/imports", content="Name\nx\n", headers={"Content-Type": "text/plain"})
    assert r.status_code == 415


def test_csv_never_creates_a_job(client, engine):
    r = upload(client, "DCREQ0009999", body(row(10001, "h1", 1)))
    assert r.status_code == 404 and r.json()["detail"]["code"] == "job_not_found"
    assert count(engine, ProjectRow) == 0 and count(engine, JobImportRow) == 0


def test_epif_file_as_cable_matrix_is_a_header_error(client):
    j = _job(client)
    r = upload(client, j["id"], body(row(10001, "h1", 1)), kind="cable_matrix")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "unknown_columns"


# ---- staging / preview ----
def test_stage_classifies_rows_and_writes_nothing_live(client, engine):
    rack, t = _env(client)
    j = _job(client)
    text = body(
        row(10001, "ready1", 1, "S1"),                         # ready (PSU items are warnings -> warning)
        row(10002, "nopos", None, "S2"),                       # held: missing RU
        row(10003, "nocab", 3, "S3", rack="R99"),              # held: unresolved cabinet
        row(10004, "noprof", 4, "S4", model="Nope"),           # held: missing profile
        row(10005, "ready1", 5, "S5"),                         # conflict: hostname repeated for R01
        row(10006, "olap", 1, "S6"),                           # conflict: RU overlap with row 1
        row(10001, "dupid", 7, "S7"),                          # conflict: repeated ePIF ID
        row(10008, "rm", 8, "S8", action="Remove"),            # held: remove not applied
        row(10009, "noserial", 9, psu1="", psu2="??"),         # warning: missing serial, PSU1 empty, PSU2 unparsed
    )
    r = upload(client, j["id"], text)
    assert r.status_code == 201, r.text
    imp = r.json()
    assert imp["status"] == "review" and imp["kind"] == "epif" and imp["filename"] == "epif.csv"
    assert imp["reupload"] is None and imp["uploaded_at"].endswith("Z")
    res = {x["hostname"] + str(x["row_number"]): x for x in imp["rows"]}
    assert [x["result"] for x in imp["rows"]] == [
        "warning", "held", "held", "held", "conflict", "conflict", "conflict", "held", "warning"]
    assert imp["counts"] == {"total": 9, "ready": 0, "warning": 2, "held": 4, "conflict": 3, "committed": 0,
                             "skipped": 0}
    codes = lambda r: {m["code"] for m in r["messages"]}  # noqa: E731
    assert "missing_position" in codes(res["nopos2"]) and "unresolved_cabinet" in codes(res["nocab3"])
    assert "missing_profile" in codes(res["noprof4"]) and "hostname_conflict" in codes(res["ready15"])
    assert "ru_overlap" in codes(res["olap6"]) and "duplicate_epif_id" in codes(res["dupid7"])
    assert "remove_not_applied" in codes(res["rm8"])
    assert {"missing_serial", "missing_psu", "psu_unparsed"} <= codes(res["noserial9"])
    assert count(engine, DeviceRow) == 0 and count(engine, EpifRequestRow) == 0
    # preview is readable by any role
    ro = client.get(f"/jobs/{j['id']}/imports/{imp['id']}")
    assert ro.status_code == 200 and len(ro.json()["rows"]) == 9


def test_db_conflicts_serial_and_placement(client, engine):
    rack, t = _env(client)
    j = _job(client)
    assert client.post("/devices", json={"host_name": "taken", "serial_number": "S1", "rack_id": rack["id"],
                                         "device_type_id": t["id"], "position_u": 10}).status_code == 201
    text = body(row(10001, "a", 1, "S1"), row(10002, "taken", 20, "S2"), row(10003, "c", 10, "S3"),
                row(10004, "d", 60, "S4"))
    rows = upload(client, j["id"], text).json()["rows"]
    got = [(x["result"], sorted(m["code"] for m in x["messages"] if m["level"] == "conflict")) for x in rows]
    assert got == [("conflict", ["serial_conflict"]), ("conflict", ["hostname_conflict"]),
                   ("conflict", ["ru_overlap"]), ("conflict", ["ru_out_of_range"])]


# ---- commit ----
def test_commit_writes_ready_skips_conflicts_with_reasons_and_resolves_epif_item(client, engine):
    rack, t = _env(client)
    j = _job(client)
    text = body(row(10001, "web01", 1, "S1"), row(10002, "web01", 2, "S2"), row(10003, "nopos", None, "S3"),
                row(10004, "web02", 3, "S4", psu1="A", psu2="zz top"))
    imp = upload(client, j["id"], text).json()
    r = client.post(f"/jobs/{j['id']}/imports/{imp['id']}/commit")
    assert r.status_code == 200, r.text
    c = r.json()
    assert [x["hostname"] for x in c["committed"]] == ["web01", "web02"]
    assert [x["hostname"] for x in c["held"]] == ["nopos"]
    assert len(c["skipped"]) == 1 and c["skipped"][0]["row_number"] == 2
    assert c["skipped"][0]["reasons"][0]["code"] == "hostname_conflict"
    assert c["imports"][0]["status"] == "committed" and c["imports"][0]["counts"]["skipped"] == 1
    assert c["job"]["device_count"] == 2 and c["open_item_count"] == c["job"]["unresolved_count"]
    # epif_not_uploaded auto-resolved; cable_matrix_not_uploaded stays
    assert len(c["resolved_item_ids"]) == 1
    items = client.get(f"/jobs/{j['id']}/open-items", params={"status": "all"}).json()
    by = {}
    for i in items:
        by.setdefault(i["item_type"], []).append(i)
    assert by["epif_not_uploaded"][0]["status"] == "resolved"
    assert by["cable_matrix_not_uploaded"][0]["status"] == "open"
    # PSU items: web01 A12/B12 -> 2 pdu_missing on the device; web02 'A' -> pdu_missing, 'zz top' -> psu_unparsed
    pdu = [(i["hostname"], i["target_field"]) for i in by["pdu_missing"]]
    assert sorted(pdu) == [("nopos", "psu_1"), ("nopos", "psu_2"), ("web01", "psu_1"), ("web01", "psu_2"),
                           ("web02", "psu_1")]
    assert by["psu_unparsed"][0]["hostname"] == "web02" and "zz top" in by["psu_unparsed"][0]["note"]
    # held row: item on the ePIF request, no device
    held = by["missing_position"][0]
    assert held["device_id"] is None and held["epif_request_id"] == c["held"][0]["epif_request_id"]
    # skipped row: 'other' item pointing at its staging row (filename joined)
    other = [i for i in by["other"] if i["import_row_id"] and i["device_id"] is None and i["epif_request_id"] is None]
    assert len(other) == 1 and other[0]["filename"] == "epif.csv"
    with Session(engine) as s:
        devs = s.exec(select(DeviceRow).order_by(DeviceRow.id)).all()
        assert [(d.host_name, d.status, d.project_id, d.position_u, d.face) for d in devs] == [
            ("web01", "install", j["id"], 1, "front"), ("web02", "install", j["id"], 3, "front")]
        reqs = s.exec(select(EpifRequestRow).order_by(EpifRequestRow.id)).all()
        assert [(q.external_id, q.status, q.dcreq) for q in reqs] == [
            ("10001", "done", "DCREQ0001234"), ("10003", "open", "DCREQ0001234"), ("10004", "done", "DCREQ0001234")]
        psus = s.exec(select(EpifPsuRow).order_by(EpifPsuRow.id)).all()
        assert [(p.psu_index, p.pdu_feed, p.pdu_port) for p in psus][:2] == [(1, "A", 12), (2, "B", 12)]
        actions = s.exec(select(AuditEventRow.action)).all()
        assert {"job_import.stage", "job_import.commit", "job_open_item.create", "device.import"} <= set(actions)
    # second commit of the same batch
    r = client.post(f"/jobs/{j['id']}/imports/{imp['id']}/commit")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "import_not_in_review"


def test_commit_revalidates_against_current_db(client, engine):
    rack, t = _env(client)
    j = _job(client)
    imp = upload(client, j["id"], body(row(10001, "late", 5, "S1"))).json()
    assert imp["rows"][0]["result"] == "warning"
    client.post("/devices", json={"host_name": "sneak", "rack_id": rack["id"], "device_type_id": t["id"],
                                  "position_u": 5})
    c = client.post(f"/jobs/{j['id']}/imports/{imp['id']}/commit").json()
    assert c["committed"] == [] and c["skipped"][0]["reasons"][0]["code"] == "ru_overlap"


def test_reupload_same_file_is_idempotent(client, engine):
    _env(client)
    j = _job(client)
    text = body(row(10001, "a", 1, "S1"))
    first = upload(client, j["id"], text)
    again = upload(client, j["id"], text)
    assert first.status_code == 201 and again.status_code == 200
    assert again.json()["id"] == first.json()["id"] and again.json()["reupload"] == "review"
    assert count(engine, ImportRowRow) == 1
    client.post(f"/jobs/{j['id']}/imports/{first.json()['id']}/commit")
    third = upload(client, j["id"], text)
    assert third.status_code == 200 and third.json()["reupload"] == "committed"
    assert third.json()["status"] == "committed" and count(engine, JobImportRow) == 1


def test_whole_job_commit_and_abandon(client, engine):
    _env(client)
    j = _job(client)
    a = upload(client, j["id"], body(row(10001, "a", 1, "S1")), filename="a.csv").json()
    b = upload(client, j["id"], body(row(10002, "b", 2, "S2")), filename="b.csv").json()
    c = upload(client, j["id"], body(row(10003, "c", 3, "S3")), filename="c.csv").json()
    r = client.post(f"/jobs/{j['id']}/imports/{c['id']}/abandon")
    assert r.status_code == 200 and r.json()["status"] == "abandoned"
    lst = client.get(f"/jobs/{j['id']}/imports")
    assert lst.headers["X-Total-Count"] == "3" and "rows" not in lst.json()[0]
    r = client.post(f"/jobs/{j['dcreq']}/commit")
    assert r.status_code == 200, r.text
    res = r.json()
    assert [i["id"] for i in res["imports"]] == [a["id"], b["id"]]
    assert {x["hostname"] for x in res["committed"]} == {"a", "b"}
    assert len({i["change_set_id"] for i in res["imports"]}) == 1
    r = client.post(f"/jobs/{j['id']}/commit")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "no_review_imports"
    # already-imported ePIF id is a conflict on a later file
    d = upload(client, j["id"], body(row(10001, "z", 9, "S9")), filename="d.csv").json()
    assert d["rows"][0]["result"] == "conflict"
    assert d["rows"][0]["messages"][0]["code"] == "epif_id_already_imported"


def test_closed_job_refuses_imports(client):
    _env(client)
    j = _job(client)
    imp = upload(client, j["id"], body(row(10001, "a", 1, "S1"))).json()
    client.post(f"/jobs/{j['id']}/close", json={"acknowledge_open_items": True})
    assert upload(client, j["id"], body(row(10002, "b", 2))).json()["detail"]["code"] == "job_closed"
    r = client.post(f"/jobs/{j['id']}/imports/{imp['id']}/commit")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "job_closed"


def test_reraise_dedupes_items(client, engine):
    _env(client)
    j = _job(client)
    a = upload(client, j["id"], body(row(10001, "held", None, "S1")), filename="a.csv").json()
    client.post(f"/jobs/{j['id']}/imports/{a['id']}/commit")
    n = count(engine, JobOpenItemRow)
    # same held row again (new ePIF id -> a new request -> its own items); same skipped conflicts reuse items
    b = upload(client, j["id"], body(row(10001, "held", None, "S1")) + "\n", filename="b.csv").json()
    client.post(f"/jobs/{j['id']}/imports/{b['id']}/commit")
    assert count(engine, JobOpenItemRow) == n + 1  # one 'other' item for the skipped repeated-ID row


# ---- open-item actions ----
def test_item_actions(client):
    j = _job(client)
    items = client.get(f"/jobs/{j['id']}/open-items").json()
    epif_item = next(i for i in items if i["item_type"] == "epif_not_uploaded")
    cab = next(i for i in items if i["item_type"] == "cable_matrix_not_uploaded")
    base = f"/jobs/{j['id']}/open-items"
    r = client.post(f"{base}/{epif_item['id']}/defer", json={"note": "file next week"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["item"]["status"] == "deferred" and out["item"]["deferred_at"].endswith("Z")
    assert out["item"]["note"] == "Deferred: file next week" and out["job"]["deferred_count"] == 1
    assert client.post(f"{base}/{epif_item['id']}/defer").json()["detail"]["code"] == "open_item_state"
    r = client.post(f"{base}/{epif_item['id']}/undefer")
    assert r.json()["item"]["status"] == "open" and r.json()["item"]["deferred_at"] is None
    assert client.post(f"{base}/{cab['id']}/undefer").json()["detail"]["code"] == "open_item_state"
    r = client.post(f"{base}/{cab['id']}/dismiss")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "note_required"
    r = client.post(f"{base}/{cab['id']}/dismiss", json={"note": "  "})
    assert r.status_code == 422
    client.post(f"{base}/{cab['id']}/defer")
    r = client.post(f"{base}/{cab['id']}/dismiss", json={"note": "no cabling on this job"})  # deferred -> dismissed
    assert r.status_code == 200, r.text
    assert r.json()["item"]["status"] == "dismissed" and r.json()["item"]["resolved_by"]
    assert r.json()["item"]["deferred_at"] is None and r.json()["item"]["note"] == "Dismissed: no cabling on this job"
    r = client.post(f"{base}/{epif_item['id']}/resolve")
    assert r.json()["item"]["status"] == "resolved" and r.json()["job"]["unresolved_count"] == 0
    assert client.post(f"{base}/{epif_item['id']}/resolve").json()["detail"]["code"] == "open_item_closed"
    assert client.post(f"{base}/999999/resolve").status_code == 404
    assert client.post(f"{base}/{cab['id']}/explode").status_code == 422
    # an item of another job
    other = _job(client, "DCREQ0005555")
    assert client.post(f"/jobs/{other['id']}/open-items/{cab['id']}/resolve").status_code == 404


# ---- roles ----
def test_readonly_can_read_but_not_write(client, client_as):
    _env(client)
    j = _job(client)
    imp = upload(client, j["id"], body(row(10001, "a", 1, "S1"))).json()
    item = client.get(f"/jobs/{j['id']}/open-items").json()[0]
    ro = client_as("read-only")
    assert ro.get(f"/jobs/{j['id']}/imports").status_code == 200
    assert ro.get(f"/jobs/{j['id']}/imports/{imp['id']}").status_code == 200
    for path in (f"/jobs/{j['id']}/imports", f"/jobs/{j['id']}/imports/{imp['id']}/commit",
                 f"/jobs/{j['id']}/imports/{imp['id']}/abandon", f"/jobs/{j['id']}/commit",
                 f"/jobs/{j['id']}/open-items/{item['id']}/resolve"):
        r = ro.post(path, content="Name\nx\n", headers=CSV)
        assert r.status_code == 403, (path, r.text)
    tech = client_as("technician")
    assert tech.post(f"/jobs/{j['id']}/imports/{imp['id']}/commit").status_code == 200


def test_parse_psu():
    from app.modules.jobs.epif import parse_psu
    assert parse_psu("A12") == ("A", 12) and parse_psu(" b-7 ") == ("B", 7) and parse_psu("A: 3") == ("A", 3)
    assert parse_psu("A") == ("A", None) and parse_psu("12") is None and parse_psu("AB12") is None


def test_ambiguous_cabinet_is_held(client):
    _env(client)
    site = client.get("/sites").json()[0]
    hall = client.post("/halls", json={"site_id": site["id"], "name": "Hall B"}).json()
    r2 = client.post("/rows", json={"hall_id": hall["id"], "name": "Row 1"}).json()
    client.post("/racks", json={"row_id": r2["id"], "name": "R01"})
    j = _job(client)
    x = upload(client, j["id"], body(row(10001, "a", 1, "S1"))).json()["rows"][0]
    m = next(m for m in x["messages"] if m["code"] == "ambiguous_cabinet")
    assert x["result"] == "held" and m["item_type"] == "unresolved_cabinet" and "Hall A, Hall B" in m["message"]
