"""Job intake v1, slice 1: DCREQ job creation, 409 duplicate, list/detail, close (acknowledgement), reopen,
the 30-day clock, roles. JOB_INTAKE.md §2/§2.1 + Preston's locked decisions (2026-11-12)."""
import re
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select, update

from app.modules.directory.models import ProjectReferenceRow, ProjectRow
from app.modules.jobs.dcreq import normalize_dcreq
from app.modules.jobs.models import JobOpenItemRow
from app.timestamps import as_utc, utcnow

ISO_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


def _job(client, dcreq="DCREQ0001234", **kw):
    r = client.post("/jobs", json={"dcreq": dcreq, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def _set(engine, job_id, **values):
    with Session(engine) as s:
        s.exec(update(ProjectRow).where(ProjectRow.id == job_id).values(**values))
        s.commit()


def _resolve_all(engine, job_id):
    with Session(engine) as s:
        s.exec(update(JobOpenItemRow).where(JobOpenItemRow.project_id == job_id)
               .values(status="resolved", resolved_at=utcnow()))
        s.commit()


# ---- DCREQ format ----
@pytest.mark.parametrize("raw,norm", [
    ("DCREQ0001234", "DCREQ0001234"), ("  dcreq0001234 ", "DCREQ0001234"), ("Dcreq0000000", "DCREQ0000000"),
])
def test_normalize_accepts(raw, norm):
    assert normalize_dcreq(raw) == norm


@pytest.mark.parametrize("raw", ["", "   ", "DCREQ001234", "DCREQ00012345", "DCREQ1001234", "DCREQ000123A",
                                 "DCREQ 0001234", "0001234", "1234", "CHG0001234", "DCREQ000١٢٣٤", None, 1234])
def test_normalize_rejects(raw):
    assert normalize_dcreq(raw) is None


@pytest.mark.parametrize("bad", ["DCREQ001234", "DCREQ000123x", "1234", "", "DCREQ0001234567"])
def test_create_bad_format_is_422_and_creates_nothing(client, engine, bad):
    r = client.post("/jobs", json={"dcreq": bad})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "dcreq_format"
    assert "input" not in r.json()["detail"]  # the value is not echoed (hint text only)
    with Session(engine) as s:
        assert s.exec(select(ProjectRow)).all() == []
        assert s.exec(select(ProjectReferenceRow)).all() == []


def test_db_check_rejects_bad_dcreq(engine):
    with Session(engine) as s:
        p = ProjectRow(name="x")
        s.add(p)
        s.flush()
        s.add(ProjectReferenceRow(project_id=p.id, kind="DCREQ", ref="DCREQ00012X4"))
        with pytest.raises(IntegrityError):
            s.flush()


# ---- create ----
def test_create_job(client, engine):
    j = _job(client, " dcreq0001234 ")
    assert j["dcreq"] == "DCREQ0001234" and j["name"] == "DCREQ0001234"
    assert j["status"] == "open" and j["current"] is True and j["overdue"] is False
    assert j["days_open"] == 0 and j["closed_at"] is None and j["recently_closed"] is False
    assert j["created_by"] == "admin1@example.com"
    for k in ("opened_at", "created_at", "updated_at", "overdue_at"):
        assert ISO_Z.match(j[k]), k
    # Both files start "not uploaded" (fill-later items, no target)
    assert j["unresolved_count"] == 2 and j["deferred_count"] == 0
    assert j["unresolved_by_type"] == {"cable_matrix_not_uploaded": 1, "epif_not_uploaded": 1}
    with Session(engine) as s:
        p = s.get(ProjectRow, j["id"])
        ref = s.get(ProjectReferenceRow, p.primary_dcreq_id)
        assert (ref.kind, ref.ref, ref.project_id) == ("DCREQ", "DCREQ0001234", p.id)
        assert p.intake_id is None
        acts = [r[0] for r in s.exec(text("SELECT action FROM audit_events WHERE entity_type = 'job'")).all()]
        assert acts == ["job.create"]


def test_create_with_name(client):
    assert _job(client, name="Leaf refresh")["name"] == "Leaf refresh"


def test_duplicate_dcreq_is_409_with_existing_job(client, engine):
    j = _job(client, name="Leaf refresh")
    r = client.post("/jobs", json={"dcreq": "dcreq0001234"})
    assert r.status_code == 409
    d = r.json()["detail"]
    assert d["code"] == "job_exists"
    assert d["existing"]["id"] == j["id"] and d["existing"]["dcreq"] == "DCREQ0001234"
    assert d["existing"]["status"] == "open" and d["existing"]["name"] == "Leaf refresh"
    assert "Leaf refresh, open" in d["message"]
    with Session(engine) as s:
        assert len(s.exec(select(ProjectRow)).all()) == 1
        assert len(s.exec(select(JobOpenItemRow)).all()) == 2  # nothing appended


def test_duplicate_of_legacy_project_reference_is_409(client):
    p = client.post("/projects", json={"name": "Legacy"}).json()
    assert client.post(f"/projects/{p['id']}/references", json={"kind": "DCREQ", "ref": "DCREQ0005555"}).status_code == 201
    d = client.post("/jobs", json={"dcreq": "DCREQ0005555"}).json()["detail"]
    assert d["code"] == "job_exists" and d["existing"]["id"] == p["id"] and d["existing"]["is_job"] is False
    # a legacy project with a DCREQ but no primary is not a job
    assert client.get("/jobs").json() == []


def test_db_unique_dcreq_backstop(engine):
    with Session(engine) as s:
        a, b = ProjectRow(name="a"), ProjectRow(name="b")
        s.add_all([a, b])
        s.flush()
        s.add(ProjectReferenceRow(project_id=a.id, kind="DCREQ", ref="DCREQ0000001"))
        s.flush()
        s.add(ProjectReferenceRow(project_id=b.id, kind="DCREQ", ref="DCREQ0000001"))
        with pytest.raises(IntegrityError):
            s.flush()


def test_reference_endpoint_keeps_dcreq_rules(client):
    j = _job(client)
    url = f"/projects/{j['id']}/references"
    r = client.post(url, json={"kind": "DCREQ", "ref": "DCREQ0009999"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "one_dcreq_per_job"
    other = client.post("/projects", json={"name": "Other"}).json()
    r = client.post(f"/projects/{other['id']}/references", json={"kind": "DCREQ", "ref": "dcreq0001234"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "job_exists"
    r = client.post(f"/projects/{other['id']}/references", json={"kind": "DCREQ", "ref": "DCREQ12"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "dcreq_format"
    # CHG refs are untouched by the DCREQ rules
    assert client.post(url, json={"kind": "CHG", "ref": "CHG0001"}).status_code == 201
    r = client.delete(f"{url}/{j['primary_dcreq_id']}")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "reference_is_job_key"


# ---- a CSV can't create a job ----
def test_no_route_creates_a_job_from_a_csv(client, engine):
    """Only POST /jobs (typed DCREQ) creates a job. The device CSV import never does, even with a DCREQ column."""
    csv = "host_name,dcreq\nsrv-1,DCREQ0007777\n"
    client.post("/devices/import", files={"file": ("d.csv", csv, "text/csv")})
    with Session(engine) as s:
        assert s.exec(select(ProjectReferenceRow)).all() == []
        assert s.exec(select(ProjectRow)).all() == []
    assert client.get("/jobs").json() == []
    # and there is no upload route on /jobs in this slice
    assert client.post("/jobs", files={"file": ("e.csv", "DCREQ\nDCREQ0007777\n", "text/csv")}).status_code == 422


# ---- read ----
def test_get_by_id_or_dcreq(client):
    j = _job(client)
    assert client.get(f"/jobs/{j['id']}").json()["id"] == j["id"]
    assert client.get("/jobs/dcreq0001234").json()["id"] == j["id"]
    assert client.get("/jobs/DCREQ0009999").status_code == 404
    assert client.get("/jobs/999").status_code == 404
    assert client.get("/jobs/nonsense").json()["detail"]["code"] == "job_not_found"


def test_soft_deleted_job_is_hidden(client):
    j = _job(client)
    assert client.delete(f"/projects/{j['id']}").status_code == 204
    assert client.get(f"/jobs/{j['id']}").status_code == 404
    assert client.get("/jobs").json() == []


def test_list_filters_search_and_paging(client, engine):
    a = _job(client, "DCREQ0000001", name="Leaf refresh")
    b = _job(client, "DCREQ0000002", name="Spine_50%")
    c = _job(client, "DCREQ0001234")
    now = utcnow()
    _set(engine, a["id"], opened_at=now - timedelta(days=45))
    _set(engine, b["id"], opened_at=now - timedelta(days=10))
    _resolve_all(engine, c["id"])
    client.post(f"/jobs/{c['id']}/close")

    r = client.get("/jobs")
    assert r.headers["X-Total-Count"] == "3"
    assert [x["id"] for x in r.json()] == [c["id"], b["id"], a["id"]]  # opened_at desc
    assert [x["id"] for x in client.get("/jobs?status=open").json()] == [b["id"], a["id"]]
    assert [x["id"] for x in client.get("/jobs?overdue=true").json()] == [a["id"]]
    assert [x["id"] for x in client.get("/jobs?recently_closed=true").json()] == [c["id"]]
    assert [x["id"] for x in client.get("/jobs?q=1234").json()] == [c["id"]]
    assert [x["id"] for x in client.get("/jobs?q=leaf").json()] == [a["id"]]
    assert [x["id"] for x in client.get("/jobs?q=50%25").json()] == [b["id"]]  # % matched literally
    assert [x["id"] for x in client.get("/jobs?q=%25").json()] == [b["id"]]
    assert [x["id"] for x in client.get("/jobs?q=_").json()] == [b["id"]]  # _ is not a wildcard
    r = client.get("/jobs?limit=1&offset=1")
    assert r.headers["X-Total-Count"] == "3" and [x["id"] for x in r.json()] == [b["id"]]


# ---- close / reopen ----
def test_close_with_open_items_needs_acknowledgement(client, engine):
    j = _job(client)
    r = client.post(f"/jobs/{j['id']}/close")
    assert r.status_code == 409
    d = r.json()["detail"]
    assert d["code"] == "job_has_open_items" and d["unresolved_count"] == 2
    r = client.post(f"/jobs/{j['id']}/close", json={"acknowledge_open_items": False})
    assert r.status_code == 409
    assert client.get(f"/jobs/{j['id']}").json()["status"] == "open"

    r = client.post(f"/jobs/{j['id']}/close", json={"acknowledge_open_items": True, "note": "vendor delay"})
    assert r.status_code == 200
    body = r.json()
    assert body["warning"]["code"] == "job_has_open_items" and body["warning"]["unresolved_count"] == 2
    job = body["job"]
    assert job["status"] == "closed" and job["current"] is False and job["recently_closed"] is True
    assert ISO_Z.match(job["closed_at"]) and job["closed_by"] == "admin1@example.com"
    assert job["days_since_closed"] == 0 and job["unresolved_count"] == 2  # items stay
    r = client.post(f"/jobs/{j['id']}/close", json={"acknowledge_open_items": True})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "job_already_closed"
    with Session(engine) as s:
        acts = [r[0] for r in s.exec(text("SELECT after_json FROM audit_events WHERE action = 'job.close'")).all()]
        assert len(acts) == 1 and '"acknowledged_open_items": true' in acts[0]


def test_close_without_open_items_needs_no_body(client, engine):
    j = _job(client)
    _resolve_all(engine, j["id"])
    r = client.post(f"/jobs/{j['id']}/close")
    assert r.status_code == 200 and r.json()["warning"] is None
    assert r.json()["job"]["status"] == "closed"


def test_deferred_items_count_as_unresolved(client, engine):
    j = _job(client)
    with Session(engine) as s:
        s.exec(update(JobOpenItemRow).where(JobOpenItemRow.project_id == j["id"],
                                            JobOpenItemRow.item_type == "epif_not_uploaded")
               .values(status="deferred", deferred_at=utcnow()))
        s.exec(update(JobOpenItemRow).where(JobOpenItemRow.project_id == j["id"],
                                            JobOpenItemRow.item_type == "cable_matrix_not_uploaded")
               .values(status="dismissed", resolved_at=utcnow(), note="no cabling"))
        s.commit()
    got = client.get(f"/jobs/{j['id']}").json()
    assert got["unresolved_count"] == 1 and got["deferred_count"] == 1
    assert client.post(f"/jobs/{j['id']}/close").json()["detail"]["unresolved_count"] == 1


def test_reopen_keeps_the_30_day_clock(client, engine):
    j = _job(client)
    opened = utcnow() - timedelta(days=31)
    _set(engine, j["id"], opened_at=opened)
    assert client.get(f"/jobs/{j['id']}").json()["overdue"] is True
    client.post(f"/jobs/{j['id']}/close", json={"acknowledge_open_items": True})
    closed = client.get(f"/jobs/{j['id']}").json()
    assert closed["overdue"] is False  # only current jobs are overdue
    r = client.post(f"/jobs/{j['id']}/reopen", json={"note": "more racks"})
    assert r.status_code == 200
    job = r.json()["job"]
    assert job["status"] == "open" and job["closed_at"] is None and job["closed_by"] is None
    assert job["opened_at"] == closed["opened_at"]
    assert job["overdue"] is True and job["days_open"] == 31
    with Session(engine) as s:
        assert abs(as_utc(s.get(ProjectRow, j["id"]).opened_at) - opened) < timedelta(seconds=1)
    assert client.post(f"/jobs/{j['id']}/reopen").json()["detail"]["code"] == "job_already_open"
    assert [x["id"] for x in client.get("/jobs?overdue=true").json()] == [j["id"]]


def test_opened_at_set_at_dcreq_entry_and_unchanged_by_close_reopen(client):
    j = _job(client)
    client.post(f"/jobs/{j['id']}/close", json={"acknowledge_open_items": True})
    client.post(f"/jobs/{j['id']}/reopen")
    assert client.get(f"/jobs/{j['id']}").json()["opened_at"] == j["opened_at"]


def test_overdue_boundary(client, engine):
    j = _job(client)
    _set(engine, j["id"], opened_at=utcnow() - timedelta(days=29, hours=23))
    assert client.get(f"/jobs/{j['id']}").json()["overdue"] is False
    _set(engine, j["id"], opened_at=utcnow() - timedelta(days=30, minutes=1))
    assert client.get(f"/jobs/{j['id']}").json()["overdue"] is True


def test_recently_closed_window(client, engine):
    j = _job(client)
    client.post(f"/jobs/{j['id']}/close", json={"acknowledge_open_items": True})
    _set(engine, j["id"], closed_at=utcnow() - timedelta(days=31))
    got = client.get(f"/jobs/{j['id']}").json()
    assert got["recently_closed"] is False and got["days_since_closed"] == 31
    assert client.get("/jobs?recently_closed=true").json() == []


def test_db_closed_check(engine):
    with Session(engine) as s:
        s.add(ProjectRow(name="x", status="closed"))
        with pytest.raises(IntegrityError):
            s.flush()


# ---- open items (read-only list in this slice) ----
def test_open_items_list(client, engine):
    j = _job(client)
    r = client.get(f"/jobs/{j['id']}/open-items")
    assert r.headers["X-Total-Count"] == "2"
    items = r.json()
    assert {i["item_type"] for i in items} == {"epif_not_uploaded", "cable_matrix_not_uploaded"}
    i = items[0]
    assert i["status"] == "open" and i["source"] == "manual" and i["dcreq"] == "DCREQ0001234"
    assert i["device_id"] is None and i["hostname"] is None and ISO_Z.match(i["created_at"])
    _resolve_all(engine, j["id"])
    assert client.get(f"/jobs/{j['id']}/open-items").json() == []
    assert len(client.get(f"/jobs/{j['id']}/open-items?status=resolved").json()) == 2
    assert len(client.get(f"/jobs/{j['id']}/open-items?status=all").json()) == 2


def test_open_item_checks(engine):
    with Session(engine) as s:
        p = ProjectRow(name="x")
        s.add(p)
        s.flush()
        s.add(JobOpenItemRow(project_id=p.id, item_type="missing_trail", source="manual"))
        s.flush()
        s.add(JobOpenItemRow(project_id=p.id, item_type="missing_trail", source="manual"))  # dedupe
        with pytest.raises(IntegrityError):
            s.flush()
        s.rollback()
    for bad in ({"status": "deferred"}, {"status": "dismissed", "resolved_at": utcnow()},
                {"item_type": "missing_dcreq"}):
        with Session(engine) as s:
            p = ProjectRow(name="y")
            s.add(p)
            s.flush()
            s.add(JobOpenItemRow(**{"project_id": p.id, "item_type": "other", "source": "manual", **bad}))
            with pytest.raises(IntegrityError):
                s.flush()


# ---- roles ----
def test_roles(client_as, anon):
    admin, tech, ro = client_as("admin"), client_as("technician"), client_as("read-only")
    assert anon.get("/jobs").status_code == 401
    assert anon.post("/jobs", json={"dcreq": "DCREQ0000001"}).status_code == 401
    r = ro.post("/jobs", json={"dcreq": "DCREQ0000001"})
    assert r.status_code == 403
    j = _job(tech, "DCREQ0000001")
    assert j["created_by"] == "technician2@example.com"
    for c in (admin, tech, ro):
        assert c.get("/jobs").status_code == 200
        assert c.get(f"/jobs/{j['id']}").status_code == 200
        assert c.get(f"/jobs/{j['id']}/open-items").status_code == 200
    assert ro.post(f"/jobs/{j['id']}/close", json={"acknowledge_open_items": True}).status_code == 403
    assert tech.post(f"/jobs/{j['id']}/close", json={"acknowledge_open_items": True}).status_code == 200
    assert ro.post(f"/jobs/{j['id']}/reopen").status_code == 403
    assert admin.post(f"/jobs/{j['id']}/reopen").status_code == 200
    assert admin.post(f"/jobs/{j['id']}/close", json={"acknowledge_open_items": True}).status_code == 200
