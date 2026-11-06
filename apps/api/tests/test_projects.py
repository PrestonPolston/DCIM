import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

CSV = {"Content-Type": "text/csv"}


def test_project_references_and_lookup(client):
    p = client.post("/projects", json={"name": "Refresh 2026", "intake_id": "INT-1", "intake_date": "2026-09-01"}).json()
    assert client.post("/projects", json={"name": "dup", "intake_id": "INT-1"}).status_code == 409
    url = f"/projects/{p['id']}/references"
    assert client.post(url, json={"kind": "CHG", "ref": "CHG0001"}).status_code == 201
    assert client.post(url, json={"kind": "CHG", "ref": "CHG0001"}).status_code == 409
    assert client.post(url, json={"kind": "XYZ", "ref": "1"}).status_code == 422
    found = client.get("/project-references?kind=chg&ref=CHG0001").json()
    assert [r["project_id"] for r in found] == [p["id"]]


def test_contacts_need_name_or_email_and_unique_email(client):
    assert client.post("/contacts", json={"phone": "123"}).status_code == 422
    v = client.post("/vendors", json={"name": "Dell"}).json()
    assert client.post("/vendors", json={"name": "DELL"}).status_code == 409
    c = client.post("/contacts", json={"email": "Jo@Vendor.com", "vendor_id": v["id"]})
    assert c.status_code == 201 and c.json()["email"] == "jo@vendor.com"
    assert client.post("/contacts", json={"email": "jo@vendor.com"}).status_code == 409
    p = client.post("/projects", json={"name": "P"}).json()
    link = client.post(f"/projects/{p['id']}/contacts", json={"contact_id": c.json()["id"], "contact_role": "vendor"})
    assert link.status_code == 201
    assert client.delete(f"/contacts/{c.json()['id']}").status_code == 409  # still on a project
    assert client.delete(f"/projects/{p['id']}/contacts/{c.json()['id']}?contact_role=vendor").status_code == 204


def test_contact_check_in_db(engine):
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO contacts (phone) VALUES ('1')"))


def test_device_project_link_api_and_csv(client):
    p = client.post("/projects", json={"name": "P", "intake_id": "INT-9"}).json()
    d = client.post("/devices", json={"host_name": "a", "project_id": p["id"]})
    assert d.status_code == 201 and d.json()["project_id"] == p["id"]
    assert client.post("/devices", json={"host_name": "b", "project_id": 999}).status_code == 404
    r = client.post("/devices/import?dry_run=false", content="host_name,project_intake_id\nc,INT-9\n", headers=CSV).json()
    assert r["created"] == 1
    bad = client.post("/devices/import?dry_run=true", content="host_name,project_intake_id\nd,NOPE\n", headers=CSV).json()
    assert "Unknown project_intake_id" in bad["errors"][0]["errors"][0]
    export = client.get("/devices/export").text
    header = export.splitlines()[0]
    assert "project_intake_id" in header and "INT-9" in export
    assert not any(pii in header for pii in ("email", "phone", "contact"))
    # deleting the project hides it; the device link stays until changed
    assert client.delete(f"/projects/{p['id']}").status_code == 204
    assert client.get(f"/projects/{p['id']}").status_code == 404
