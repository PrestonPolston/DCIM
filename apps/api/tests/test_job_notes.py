"""Job-intake text rules.

Note fields (open-item actions, job close/reopen): LF and tab allowed, CRLF stored as LF, every other control
character (lone CR, NUL, ESC, VT, FF, DEL, ...) is a coded 422 invalid_text. Notes may start with = + - @ (every
CSV export neutralises formula cells on output). Job name/description/dcreq stay single line and keep the formula
guard; every rejection is {detail: {code, message, field}}."""
import json

import pytest
from sqlmodel import Session, select

from app.modules.audit.models import AuditEventRow
from app.modules.history.models import ChangeSetRow
from app.modules.jobs.models import JobOpenItemRow

BAD = ["a\rb", "a\x00b", "a\x1bb", "a\x7fb", "a\x0bb", "a\x0cb", "line1\r\n\x00line2", "a\r\rb"]


def _job(client):
    r = client.post("/jobs", json={"dcreq": "DCREQ0001234"})
    assert r.status_code == 201, r.text
    return r.json()


def _items(client, j):
    return {i["item_type"]: i for i in client.get(f"/jobs/{j['id']}/open-items").json()}


@pytest.mark.parametrize("action", ["defer", "dismiss", "resolve"])
def test_item_note_multiline_crlf_stored_as_lf(client, engine, action):
    j = _job(client)
    item = _items(client, j)["epif_not_uploaded"]
    r = client.post(f"/jobs/{j['id']}/open-items/{item['id']}/{action}",
                    json={"note": "vendor ships Friday\r\nPDU map to follow\nsee ticket"})
    assert r.status_code == 200, r.text
    note = r.json()["item"]["note"]
    assert note.endswith(": vendor ships Friday\nPDU map to follow\nsee ticket") and "\r" not in note
    with Session(engine) as s:
        assert "\r" not in s.get(JobOpenItemRow, item["id"]).note


def test_undefer_note_multiline(client):
    j = _job(client)
    item = _items(client, j)["epif_not_uploaded"]
    client.post(f"/jobs/{j['id']}/open-items/{item['id']}/defer")
    r = client.post(f"/jobs/{j['id']}/open-items/{item['id']}/undefer", json={"note": "back\r\non"})
    assert r.status_code == 200 and r.json()["item"]["note"] == "Reopened: back\non"


@pytest.mark.parametrize("bad", BAD)
def test_item_note_other_control_characters_422(client, engine, bad):
    j = _job(client)
    item = _items(client, j)["epif_not_uploaded"]
    for action in ("defer", "dismiss", "resolve"):
        r = client.post(f"/jobs/{j['id']}/open-items/{item['id']}/{action}", json={"note": bad})
        assert r.status_code == 422, (action, repr(bad), r.text)
        assert r.json() == {"detail": {"code": "invalid_text", "field": "note", "message":
                                       "note must not contain control characters other than line breaks and tabs"}}
    with Session(engine) as s:
        assert s.get(JobOpenItemRow, item["id"]).status == "open"


def test_dismiss_note_of_only_line_breaks_is_still_required(client):
    j = _job(client)
    item = _items(client, j)["cable_matrix_not_uploaded"]
    r = client.post(f"/jobs/{j['id']}/open-items/{item['id']}/dismiss", json={"note": "\r\n\n"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "note_required"


def test_close_and_reopen_notes_multiline(client, engine):
    j = _job(client)
    r = client.post(f"/jobs/{j['id']}/close", json={"acknowledge_open_items": True, "note": "done\r\nleft 2 items"})
    assert r.status_code == 200, r.text
    r = client.post(f"/jobs/{j['id']}/reopen", json={"note": "vendor back\r\nnew PDU"})
    assert r.status_code == 200, r.text
    with Session(engine) as s:
        notes = set(s.exec(select(ChangeSetRow.note)).all())
        assert {"done\nleft 2 items", "vendor back\nnew PDU"} <= notes
        audits = {a.action: json.loads(a.after_json)
                  for a in s.exec(select(AuditEventRow).where(AuditEventRow.action.in_(["job.close", "job.reopen"])))}
        assert audits["job.close"]["note"] == "done\nleft 2 items"
        assert audits["job.reopen"]["note"] == "vendor back\nnew PDU"


@pytest.mark.parametrize("bad", BAD)
def test_close_reopen_other_control_characters_422(client, bad):
    j = _job(client)
    r = client.post(f"/jobs/{j['id']}/close", json={"acknowledge_open_items": True, "note": bad})
    assert r.status_code == 422, (repr(bad), r.text)
    assert r.json()["detail"]["code"] == "invalid_text" and r.json()["detail"]["field"] == "note"
    assert client.get(f"/jobs/{j['id']}").json()["status"] == "open"
    client.post(f"/jobs/{j['id']}/close", json={"acknowledge_open_items": True})
    r = client.post(f"/jobs/{j['id']}/reopen", json={"note": bad})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_text"


def test_tab_allowed_in_notes(client, engine):
    j = _job(client)
    item = _items(client, j)["epif_not_uploaded"]
    r = client.post(f"/jobs/{j['id']}/open-items/{item['id']}/defer", json={"note": "rack\tU12\r\n\tPSU2\tmissing"})
    assert r.status_code == 200, r.text
    assert r.json()["item"]["note"].endswith("rack\tU12\n\tPSU2\tmissing")
    r = client.post(f"/jobs/{j['id']}/close", json={"acknowledge_open_items": True, "note": "a\tb"})
    assert r.status_code == 200, r.text
    assert client.post(f"/jobs/{j['id']}/reopen", json={"note": "c\td\ne"}).status_code == 200
    with Session(engine) as s:
        assert {"a\tb", "c\td\ne"} <= set(s.exec(select(ChangeSetRow.note)).all())


@pytest.mark.parametrize("note", ["=SUM(A1)", "+1 spare optic", "-48V DC feed", "@vendor please check"])
def test_notes_may_start_with_formula_characters(client, note):
    j = _job(client)
    item = _items(client, j)["epif_not_uploaded"]
    for action in ("defer", "undefer"):
        r = client.post(f"/jobs/{j['id']}/open-items/{item['id']}/{action}", json={"note": note})
        assert r.status_code == 200, (action, r.text)
    r = client.post(f"/jobs/{j['id']}/open-items/{item['id']}/dismiss", json={"note": note})
    assert r.status_code == 200 and r.json()["item"]["note"].endswith(note)
    assert client.post(f"/jobs/{j['id']}/close", json={"acknowledge_open_items": True, "note": note}).status_code == 200
    assert client.post(f"/jobs/{j['id']}/reopen", json={"note": note}).status_code == 200


def test_formula_cells_neutralised_on_every_csv_export():
    """The reason notes may skip the input guard: every CSV writer prefixes ' on formula cells."""
    from app.modules.devices.csv_io import neutralize
    from app.validation import neutralize_cell
    for v in ("=SUM(A1)", "+1", "-48V", "@x", "\tx", "\rx"):
        assert neutralize(v) == "'" + v and neutralize_cell(v) == "'" + v
    assert neutralize("ok\n=x") == "ok\n=x"


@pytest.mark.parametrize("field", ["name", "description"])
@pytest.mark.parametrize("bad", ["a\nb", "a\r\nb", "a\rb", "a\tb", "a\x00b", "a\x7fb"])
def test_job_name_and_description_single_line_coded_422(client, field, bad):
    r = client.post("/jobs", json={"dcreq": "DCREQ0001234", field: bad})
    assert r.status_code == 422, r.text
    assert r.json() == {"detail": {"code": "invalid_text", "field": field, "message":
                                   f"{field} must not contain control characters (it must be a single line)"}}
    assert client.get("/jobs").json() == []


@pytest.mark.parametrize("field", ["name", "description"])
@pytest.mark.parametrize("bad", ["=SUM(A1)", "+1", "-x", "@x"])
def test_job_name_and_description_keep_formula_guard_coded_422(client, field, bad):
    r = client.post("/jobs", json={"dcreq": "DCREQ0001234", field: bad})
    assert r.status_code == 422, r.text
    assert r.json() == {"detail": {"code": "formula_prefix", "field": field,
                                   "message": f"{field} must not start with = + - @ (spreadsheet formula)"}}


def test_dcreq_control_character_coded_422(client):
    r = client.post("/jobs", json={"dcreq": "DCREQ\x000001234"})
    assert r.status_code == 422 and r.json()["detail"] == {
        "code": "invalid_text", "field": "dcreq",
        "message": "dcreq must not contain control characters (it must be a single line)"}


def test_coded_422_never_echoes_the_value(client):
    r = client.post("/jobs", json={"dcreq": "DCREQ0001234", "name": "=HYPERLINK(\"http://evil\")"})
    assert r.status_code == 422 and "evil" not in r.text


def test_other_models_keep_the_generic_422_list(client):
    """Only job-intake models opted in; e.g. a location create still returns the pydantic list, and refuses = ."""
    r = client.post("/sites", json={"name": "=x"})
    assert r.status_code == 422 and isinstance(r.json()["detail"], list)
    assert "spreadsheet formula" in r.json()["detail"][0]["msg"]


def test_non_text_job_errors_unchanged(client):
    r = client.post("/jobs", json={"dcreq": "DCREQ0001234", "bogus": 1})
    assert r.status_code == 422 and isinstance(r.json()["detail"], list)
