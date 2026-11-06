"""P1-10: device_ru_slots (DB-level no-overlap), racks.hall_id, status-history backfill (p1_23..p1_25)."""
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.db import make_engine
from app.modules.devices.models import DeviceRow
from app.modules.devices.slots import DeviceRuSlotRow
from tests.conftest import TEST_DATABASE_URL, reset_postgres
from tests.test_locations import make_rack, publish_profile


def _profile(client, name, u, full_depth=True):
    t = client.post("/device-types", json={"manufacturer": "S", "name": name, "u_height": u,
                                           "asset_type": "server"}).json()
    p = client.post(f"/device-types/{t['id']}/profiles", json={"name": "p", "is_full_depth": full_depth}).json()
    publish_profile(client, t["id"], p["id"])
    return p["id"]


def _slots(engine, device_id=None):
    with Session(engine) as s:
        q = select(DeviceRuSlotRow.rack_id, DeviceRuSlotRow.u, DeviceRuSlotRow.side)
        if device_id is not None:
            q = q.where(DeviceRuSlotRow.device_id == device_id)
        return sorted(s.exec(q).all())


def test_slots_follow_every_write(client, engine):
    rack = make_rack(client, u_height=10)
    rid = rack["id"]
    full = _profile(client, "Full2U", 2)
    half = _profile(client, "Half1U", 1, full_depth=False)
    a = client.post("/devices", json={"host_name": "a", "profile_id": full, "rack_id": rid, "position_u": 1}).json()
    assert _slots(engine, a["id"]) == [(rid, 1, "front"), (rid, 1, "rear"), (rid, 2, "front"), (rid, 2, "rear")]
    b = client.post("/devices", json={"host_name": "b", "profile_id": half, "rack_id": rid, "position_u": 5,
                                      "face": "rear"}).json()
    c = client.post("/devices", json={"host_name": "c", "profile_id": half, "rack_id": rid, "position_u": 5,
                                      "face": "front"}).json()
    assert _slots(engine, b["id"]) == [(rid, 5, "rear")] and _slots(engine, c["id"]) == [(rid, 5, "front")]
    assert client.patch(f"/devices/{a['id']}", json={"position_u": 7}).status_code == 200  # move
    assert _slots(engine, a["id"]) == [(rid, 7, "front"), (rid, 7, "rear"), (rid, 8, "front"), (rid, 8, "rear")]
    assert client.patch(f"/devices/{b['id']}", json={"face": "front", "position_u": 6}).status_code == 200
    assert _slots(engine, b["id"]) == [(rid, 6, "front")]
    assert client.patch(f"/devices/{c['id']}", json={"status": "decom"}).status_code == 200  # D2 unracks
    assert _slots(engine, c["id"]) == []
    assert client.delete(f"/devices/{b['id']}").status_code == 204  # soft delete = decom
    assert _slots(engine, b["id"]) == []
    r = client.post("/devices/import?dry_run=false", content=f"host_name,profile_id,rack_id,position_u\n"
                    f"csv-1,{half},{rid},3\n", headers={"content-type": "text/csv"})
    assert r.status_code == 200, r.text
    with Session(engine) as s:
        csv_id = s.exec(select(DeviceRow.id).where(DeviceRow.host_name == "csv-1")).one()
    assert _slots(engine, csv_id) == [(rid, 3, "front")]
    assert client.delete(f"/racks/{rid}").status_code == 204  # D3: every device decom'd -> no slots
    assert _slots(engine) == []


def test_db_refuses_overlap_that_skips_the_python_check(client, engine):
    rack = make_rack(client, u_height=10)
    prof = _profile(client, "Full1U", 1)
    client.post("/devices", json={"host_name": "x", "profile_id": prof, "rack_id": rack["id"], "position_u": 4})
    with Session(engine) as s:  # e.g. a concurrent writer that read before x committed
        s.add(DeviceRow(host_name="y", profile_id=prof, rack_id=rack["id"], position_u=4))
        with pytest.raises(IntegrityError):
            s.commit()


def test_rack_hall_id(client, engine):
    rack = make_rack(client)
    row = client.get(f"/rows/{rack['row_id']}").json()
    assert rack["hall_id"] == row["hall_id"]
    assert client.get(f"/racks/{rack['id']}").json()["hall_id"] == row["hall_id"]
    with engine.begin() as c:  # floor cell unique per hall among live racks, at the DB level
        c.execute(text("UPDATE racks SET pos_x = 1, pos_y = 1 WHERE id = :i"), {"i": rack["id"]})
    other = client.post("/racks", json={"row_id": rack["row_id"], "name": "R02"}).json()
    with pytest.raises(IntegrityError), engine.begin() as c:
        c.execute(text("UPDATE racks SET pos_x = 1, pos_y = 1 WHERE id = :i"), {"i": other["id"]})
    with engine.begin() as c:
        c.execute(text("UPDATE racks SET deleted_at = CURRENT_TIMESTAMP WHERE id = :i"), {"i": rack["id"]})
        c.execute(text("UPDATE racks SET pos_x = 1, pos_y = 1 WHERE id = :i"), {"i": other["id"]})


def _seed_p1_22(c):
    c.execute(text("INSERT INTO halls(site_id, name) VALUES ((SELECT min(id) FROM sites), 'H')"))
    c.execute(text("INSERT INTO rows(hall_id, name) VALUES ((SELECT min(id) FROM halls), 'R')"))
    c.execute(text("INSERT INTO racks(row_id, name, pos_x, pos_y) VALUES ((SELECT min(id) FROM rows), 'K', 0, 0)"))
    c.execute(text("INSERT INTO device_types(manufacturer, name, u_height, is_full_depth, asset_type) "
                   "VALUES ('A', 'T', 2, true, 'server')"))
    c.execute(text("INSERT INTO device_type_profiles(device_type_id, name, is_default, u_height, is_full_depth) "
                   "VALUES ((SELECT min(id) FROM device_types), 'full', true, 2, true), "
                   "((SELECT min(id) FROM device_types), 'half', false, 1, false)"))
    full = "(SELECT id FROM device_type_profiles WHERE name='full')"
    half = "(SELECT id FROM device_type_profiles WHERE name='half')"
    k = "(SELECT id FROM racks WHERE name='K')"
    t = "(SELECT min(id) FROM device_types)"
    c.execute(text(f"INSERT INTO devices(host_name, status, face, device_type_id, profile_id, rack_id, position_u) "
                   f"VALUES ('d1', 'active', 'front', {t}, {full}, {k}, 1), "
                   f"('d2', 'active', 'rear', {t}, {half}, {k}, 3), "
                   f"('d3', 'install', 'front', {t}, {half}, NULL, NULL)"))
    c.execute(text("INSERT INTO device_status_history(device_id, from_status, to_status) "
                   "VALUES ((SELECT id FROM devices WHERE host_name='d1'), NULL, 'active')"))


def test_p1_23_to_p1_25_data_steps(tmp_path, monkeypatch):
    url = TEST_DATABASE_URL or f"sqlite:///{tmp_path / 'p110.db'}"
    if TEST_DATABASE_URL:
        reset_postgres(url)
    monkeypatch.setenv("DCIM_DATABASE_URL", url)
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "p1_22_profile_image_tex")
    eng = make_engine(url)
    with eng.begin() as c:
        _seed_p1_22(c)
    command.upgrade(cfg, "head")
    with eng.begin() as c:
        slots = sorted(tuple(r) for r in c.execute(text(
            "SELECT d.host_name, s.u, s.side FROM device_ru_slots s JOIN devices d ON d.id = s.device_id")))
        assert slots == [("d1", 1, "front"), ("d1", 1, "rear"), ("d1", 2, "front"), ("d1", 2, "rear"),
                         ("d2", 3, "rear")]
        assert c.execute(text("SELECT r.hall_id = w.hall_id FROM racks r JOIN rows w ON w.id = r.row_id")).scalar()
        hist = dict(c.execute(text("SELECT d.host_name, count(h.id) FROM devices d LEFT JOIN device_status_history h "
                                   "ON h.device_id = d.id GROUP BY d.host_name")).all())
        assert hist == {"d1": 1, "d2": 1, "d3": 1}
        assert c.execute(text("SELECT to_status FROM device_status_history h JOIN devices d ON d.id = h.device_id "
                              "WHERE d.host_name = 'd3'")).scalar() == "install"
    command.downgrade(cfg, "p1_22_profile_image_tex")
    with eng.begin() as c:
        assert c.execute(text("SELECT count(*) FROM device_status_history")).scalar() == 1  # only the real one
        assert c.execute(text("SELECT count(*) FROM devices")).scalar() == 3
    command.upgrade(cfg, "head")
    eng.dispose()


def test_p1_23_refuses_overlapping_data(tmp_path, monkeypatch):
    url = TEST_DATABASE_URL or f"sqlite:///{tmp_path / 'ov.db'}"
    if TEST_DATABASE_URL:
        reset_postgres(url)
    monkeypatch.setenv("DCIM_DATABASE_URL", url)
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "p1_22_profile_image_tex")
    eng = make_engine(url)
    with eng.begin() as c:
        _seed_p1_22(c)
        c.execute(text("UPDATE devices SET rack_id = (SELECT id FROM racks WHERE name='K'), position_u = 2 "
                       "WHERE host_name = 'd3'"))
    with pytest.raises(RuntimeError, match="overlapping"):
        command.upgrade(cfg, "head")
    with eng.begin() as c:  # nothing changed
        assert c.execute(text("SELECT count(*) FROM devices")).scalar() == 3
    eng.dispose()


def test_p1_26_placement_history_backfill(tmp_path, monkeypatch):
    url = TEST_DATABASE_URL or f"sqlite:///{tmp_path / 'ph.db'}"
    if TEST_DATABASE_URL:
        reset_postgres(url)
    monkeypatch.setenv("DCIM_DATABASE_URL", url)
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "p1_22_profile_image_tex")
    eng = make_engine(url)
    with eng.begin() as c:
        _seed_p1_22(c)  # d1 + d2 placed, d3 unplaced
    command.upgrade(cfg, "p1_25_device_history_backfill")
    with eng.begin() as c:
        c.execute(text("INSERT INTO device_placement_history(device_id, to_rack_id, to_position_u, to_face, reason) "
                       "SELECT id, rack_id, 1, 'front', 'real move' FROM devices WHERE host_name = 'd1'"))
        before = c.execute(text("SELECT id, rack_id, position_u, face, updated_at FROM devices ORDER BY id")).all()
    command.upgrade(cfg, "head")
    q = ("SELECT d.host_name, h.reason, h.to_position_u, h.to_face, h.from_rack_id, h.changed_by, cs.source "
         "FROM device_placement_history h JOIN devices d ON d.id = h.device_id "
         "LEFT JOIN change_sets cs ON cs.id = h.change_set_id ORDER BY d.host_name")
    with eng.begin() as c:
        rows = [tuple(r) for r in c.execute(text(q))]
        assert rows == [("d1", "real move", 1, "front", None, None, None),
                        ("d2", "p1_26 backfill", 3, "rear", None, None, "migration")]
        assert c.execute(text("SELECT id, rack_id, position_u, face, updated_at FROM devices ORDER BY id")).all() == before
    command.downgrade(cfg, "p1_25_device_history_backfill")
    with eng.begin() as c:
        assert [r[0] for r in c.execute(text("SELECT reason FROM device_placement_history"))] == ["real move"]
    command.upgrade(cfg, "head")
    with eng.begin() as c:  # re-run adds exactly one again (idempotent per device)
        assert c.execute(text("SELECT count(*) FROM device_placement_history")).scalar() == 2
    eng.dispose()


def test_floor_cell_race_maps_to_409_code(client, monkeypatch):
    rack = make_rack(client)
    client.patch(f"/racks/{rack['id']}", json={"pos_x": 2, "pos_y": 3})
    other = client.post("/racks", json={"row_id": rack["row_id"], "name": "R02"}).json()
    from app.modules.locations import router as loc
    monkeypatch.setattr(loc, "ensure_floor_spot_free", lambda *a, **k: None)  # a writer that read before
    r = client.patch(f"/racks/{other['id']}", json={"pos_x": 2, "pos_y": 3})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "floor_position_taken", r.text
    r = client.post("/racks", json={"row_id": rack["row_id"], "name": "R03", "pos_x": 2, "pos_y": 3})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "floor_position_taken", r.text


def test_slot_race_maps_to_409_code(client, engine):
    from fastapi import HTTPException
    from app.db import commit_or_409
    rack = make_rack(client, u_height=10)
    prof = _profile(client, "Race1U", 1)
    client.post("/devices", json={"host_name": "x", "profile_id": prof, "rack_id": rack["id"], "position_u": 4})
    with Session(engine) as s:
        s.add(DeviceRow(host_name="y", profile_id=prof, rack_id=rack["id"], position_u=4))
        with pytest.raises(HTTPException) as e:
            commit_or_409(s, "x")
    assert e.value.status_code == 409 and e.value.detail["code"] == "ru_slot_taken"


def test_guard_no_bulk_placement_writes():
    """device_ru_slots is synced by an ORM flush hook; Core UPDATE/INSERT on devices bypasses it.
    Fail if app code or scripts bulk-write a placement column on devices."""
    import pathlib
    import re
    root = pathlib.Path(__file__).parents[1]
    bad = []
    for f in [p for p in list((root / "app").rglob("*.py")) + list((root / "scripts").rglob("*.py")) if p.name != "slots.py"]:
        src = f.read_text()
        for m in re.finditer(r"(update|insert)\(DeviceRow\)(.{0,400})", src, re.S):
            if re.search(r"\b(rack_id|position_u|face|profile_id)\s*=(?!=)", m.group(2).split("\n\n")[0]):
                bad.append(f"{f.relative_to(root)}: {m.group(0)[:80]!r}")
        if re.search(r"UPDATE devices SET[^\"']*(rack_id|position_u|face|profile_id)", src, re.I):
            bad.append(str(f.relative_to(root)))
    assert not bad, bad
