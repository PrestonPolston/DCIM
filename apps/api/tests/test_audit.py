import json

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlmodel import Session, select

from app.modules.audit.models import AuditEventRow
from tests.test_locations import dtype, make_rack, place


def events(engine, prefix=""):
    with Session(engine) as s:
        rows = s.exec(select(AuditEventRow).order_by(AuditEventRow.id)).all()
    return [e for e in rows if e.action.startswith(prefix)]


def test_device_install_move_decom_audited(client, engine):
    rack = make_rack(client)
    rack2 = client.post("/racks", json={"row_id": rack["row_id"], "name": "R2"}).json()
    d = place(client, rack, dtype(client, 1), 1, host="web").json()
    client.patch(f"/devices/{d['id']}", json={"rack_id": rack2["id"], "position_u": 7})
    client.patch(f"/devices/{d['id']}", json={"status": "decom"})
    evs = events(engine, "device.")
    assert [e.action for e in evs] == ["device.install", "device.move", "device.decom"]
    move = evs[1]
    assert json.loads(move.before_json) == {"rack_id": rack["id"], "position_u": 1}
    assert json.loads(move.after_json) == {"rack_id": rack2["id"], "position_u": 7}
    me = client.get("/auth/me").json()
    assert move.actor_user_id == me["id"] and move.actor_ip and move.request_id


def test_failed_request_leaves_no_event(client, engine):
    rack = make_rack(client, u_height=2)
    before = len(events(engine, "device."))
    assert place(client, rack, dtype(client, 2), 2).status_code == 409
    assert len(events(engine, "device.")) == before


def test_import_events_share_batch(client, engine):
    r = client.post("/devices/import?dry_run=false", content="host_name\na\nb\n",
                    headers={"Content-Type": "text/csv"})
    assert r.json()["created"] == 2
    evs = events(engine, "device.import")
    assert len(evs) == 3 and len({e.import_batch_id for e in evs}) == 1  # 2 rows + summary


def test_location_and_device_type_changes_audited(client, engine):
    site = client.post("/sites", json={"name": "S"}).json()
    client.patch(f"/sites/{site['id']}", json={"name": "S2"})
    client.post("/device-types", json={"manufacturer": "A", "name": "B"})
    acts = [e.action for e in events(engine)]
    assert {"location.site.create", "location.site.update", "device_type.create"} <= set(acts)


def test_audit_events_are_append_only(client, engine):
    client.post("/sites", json={"name": "S"})
    for sql in ("UPDATE audit_events SET action = 'x'", "DELETE FROM audit_events"):
        with pytest.raises(DBAPIError, match="append-only"):
            with engine.begin() as conn:
                conn.execute(text(sql))


def test_audit_events_endpoint(client):
    client.post("/sites", json={"name": "S"})
    r = client.get("/audit-events", params={"entity_type": "site"})
    assert r.status_code == 200 and r.json()[0]["action"] == "location.site.create"


def test_archive_then_purge(client, engine, tmp_path):
    from datetime import timedelta

    from app.scripts.audit_archive import run
    from app.timestamps import utcnow

    client.post("/sites", json={"name": "S"})
    with engine.begin() as conn:  # backdate everything (guard lifted just for the test)
        from app.modules.audit.guards import create_append_only_guards, drop_append_only_guards
        drop_append_only_guards(conn)
        conn.execute(text("UPDATE audit_events SET occurred_at = :t"), {"t": utcnow() - timedelta(days=500)})
        create_append_only_guards(conn)
    old = len(events(engine))
    out = tmp_path / "archive.jsonl"
    assert run(out, purge=False, months=13, engine=engine) == old
    assert len(events(engine)) == old  # archive only
    assert run(out, purge=True, months=13, engine=engine) == old
    assert out.read_text().count("\n") == 2 * old
    assert [e.action for e in events(engine)] == ["audit.purge"]
    import hashlib, json, os, stat
    after = json.loads(events(engine)[0].after_json)
    assert after["archive_sha256"] == hashlib.sha256(out.read_bytes()).hexdigest() and after["actor"]
    assert stat.S_IMODE(os.stat(out).st_mode) == 0o600
    with pytest.raises(DBAPIError):  # guard is back
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM audit_events"))
    assert run(out, purge=True, months=0, engine=engine) == 0


def test_purge_keeps_restorable_snapshots_24_months(client, engine, tmp_path):
    from datetime import timedelta

    from app.modules.audit.guards import create_append_only_guards, drop_append_only_guards
    from app.scripts.audit_archive import run
    from app.timestamps import utcnow

    with engine.begin() as conn:
        drop_append_only_guards(conn)
        conn.execute(text("DELETE FROM audit_events"))
        for action, cls, days in (("std-old", "standard", 500), ("snap-20m", "restorable", 600),
                                  ("snap-30m", "restorable", 900), ("std-new", "standard", 10)):
            conn.execute(text("INSERT INTO audit_events(occurred_at, action, entity_type, retention_class) "
                              "VALUES (:t, :a, 'device', :c)"), {"t": utcnow() - timedelta(days=days), "a": action, "c": cls})
        create_append_only_guards(conn)
    out = tmp_path / "a.jsonl"
    # a setting below 24 is raised to 24
    assert run(out, purge=True, months=13, engine=engine, restorable_months=6) == 2
    left = {e.action for e in events(engine)}
    assert left == {"snap-20m", "std-new", "audit.purge"}
    import json
    purge = next(e for e in events(engine) if e.action == "audit.purge")
    assert json.loads(purge.after_json)["restorable_deleted"] == 1 and purge.retention_class == "standard"
    # 0 = keep restorable forever; 36 = keep the 20-month snapshot
    assert run(out, purge=True, months=13, engine=engine, restorable_months=0) == 0
    assert run(out, purge=True, months=13, engine=engine, restorable_months=36) == 0
    assert "snap-20m" in {e.action for e in events(engine)}
