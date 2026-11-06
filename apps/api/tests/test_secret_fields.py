import logging

import pytest
from sqlmodel import Session, select

from app.modules.audit.models import AuditEventRow
from app.validation import is_secret_name

SECRET = "iLo-Pa55-zzq-777"
CSV = {"Content-Type": "text/csv"}


@pytest.mark.parametrize("name", ["ilo_password", "ilo_pass", "password", "passwd", "secret", "community",
                                  "bmc_password", "snmp_community", "api_token", "Token", "ILO_PASSWORD"])
def test_deny_list_matches(name):
    assert is_secret_name(name)


@pytest.mark.parametrize("name", ["host_name", "serial_number", "description", "passive", "secretary_notes"])
def test_deny_list_allows(name):
    assert not is_secret_name(name)


@pytest.mark.parametrize("field", ["ilo_password", "password", "secret", "community", "idrac_password"])
def test_api_rejects_secret_fields(client, field, caplog, engine):
    caplog.set_level(logging.DEBUG)
    r = client.post("/devices", json={"host_name": "h", field: SECRET})
    assert r.status_code == 422
    assert r.json()["detail"][0]["type"] == "secret_field_not_accepted"
    assert field in r.json()["detail"][0]["msg"]
    r2 = client.patch("/devices/1", json={field: SECRET})
    assert r2.status_code in (404, 422)
    assert SECRET not in r.text + r2.text + caplog.text
    with Session(engine) as s:
        assert all(SECRET not in (e.before_json or "") + (e.after_json or "")
                   for e in s.exec(select(AuditEventRow)).all())


def test_csv_with_secret_header_rejected(client, caplog, engine):
    caplog.set_level(logging.DEBUG)
    body = f"host_name,ilo_password\nh1,{SECRET}\n"
    r = client.post("/devices/import?dry_run=false", content=body, headers=CSV)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "secret_field_not_accepted"
    assert "ilo_password" in r.json()["detail"]["message"] and SECRET not in r.text + caplog.text
    assert client.get("/devices").json() == []
    with Session(engine) as s:
        assert all(SECRET not in (e.after_json or "") for e in s.exec(select(AuditEventRow)).all())


def test_declared_password_fields_still_work(client):
    r = client.post("/users", json={"email": "t@example.com", "display_name": "T", "role": "read-only",
                                    "temporary_password": "a-very-long-pass-123"})
    assert r.status_code == 201, r.text


# N-5: the labels Preston's spreadsheets actually use
REAL_LABELS = ["iLO password", "ILO PW", "ilo_pw", "ilo-password", "ilo-pw", "BMC Password", "iLOPassword",
               "Pass", "pw", "PWD", "passwd", "iDRAC  Pass", "SNMP-Community", "API Key", "root_pass"]


@pytest.mark.parametrize("name", REAL_LABELS)
def test_deny_list_matches_real_labels(name):
    assert is_secret_name(name)


@pytest.mark.parametrize("name", ["Host Name", "power_assignment", "passive", "secretary_notes", "Serial-Number",
                                  "app_service", "compass_rack", "bypass"])
def test_deny_list_normalised_allows(name):
    assert not is_secret_name(name)


@pytest.mark.parametrize("field", ["iLO password", "ILO PW", "ilo_pw", "ilo-password"])
def test_api_rejects_real_labels(client, field):
    r = client.post("/devices", json={"host_name": "h", field: SECRET})
    assert r.status_code == 422
    assert r.json()["detail"][0]["type"] == "secret_field_not_accepted"
    assert SECRET not in r.text


@pytest.mark.parametrize("header", ["iLO password", "ILO PW", "ilo_pw", "ilo-password"])
def test_csv_rejects_real_labels(client, engine, header):
    body = f"host_name,{header}\nh1,{SECRET}\n"
    r = client.post("/devices/import?dry_run=false", content=body, headers=CSV)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "secret_field_not_accepted"
    assert SECRET not in r.text
    with Session(engine) as s:
        from app.modules.devices.models import DeviceRow
        assert s.exec(select(DeviceRow)).all() == []
