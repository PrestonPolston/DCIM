import importlib.util
from pathlib import Path

import pytest
from sqlmodel import Session, func, select

from app.modules.auth.models import UserRow
from app.modules.devices.models import DeviceRow
from app.modules.locations.models import RackRow, RackRowRow

spec = importlib.util.spec_from_file_location("seed_demo", Path(__file__).parents[1] / "scripts" / "seed_demo.py")
seed_demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed_demo)


def counts(engine):
    with Session(engine) as s:
        c = lambda m: s.exec(select(func.count()).select_from(m)).one()  # noqa: E731
        return {"rows": c(RackRowRow), "racks": c(RackRow), "devices": c(DeviceRow), "users": c(UserRow)}


def test_seed_twice_is_idempotent_and_reseed_works(engine):
    first = seed_demo.run(engine)
    assert first["racks"] == 420 and first["rows"] == 30 and 40 <= first["devices"] <= 60
    assert 10 <= first["device_types"] <= 15 and first["users"] == 3
    after_first = counts(engine)
    second = seed_demo.run(engine)
    assert all(v == 0 for v in second.values()) and counts(engine) == after_first
    third = seed_demo.run(engine, reseed=True)
    assert third["racks"] == 420 and third["devices"] == first["devices"] and third["users"] == 0
    assert counts(engine) == after_first


def test_seed_data_is_valid(engine):
    seed_demo.run(engine)
    with Session(engine) as s:
        racks = s.exec(select(RackRow)).all()
        assert len({(r.pos_x, r.pos_y) for r in racks}) == len(racks)  # no shared floor cell
        devices = s.exec(select(DeviceRow)).all()
        assert all(d.rack_id is None for d in devices if d.status == "decom")
        assert {d.status for d in devices} == {"install", "active", "decom"}
        racked = [(d.rack_id, d.host_name.lower()) for d in devices if d.rack_id]
        assert all(d.profile_id and d.device_type_id for d in devices if d.rack_id)
        assert len(set(racked)) == len(racked)


def test_layout_two_banks_center_aisle(engine):
    seed_demo.run(engine)
    with Session(engine) as s:
        rows = {r.name: r for r in s.exec(select(RackRowRow)).all()}
        racks = s.exec(select(RackRow)).all()
    for n in range(1, 31):
        row = rows[f"R{n:02d}"]
        assert row.orientation == ("E" if n % 2 else "W")  # fronts face the center aisle
    for k in range(1, 16):
        odd, even = rows[f"R{2*k-1:02d}"], rows[f"R{2*k:02d}"]
        assert odd.pos_y == even.pos_y  # facing pair shares its position along the row axis
        assert odd.pos_x < even.pos_x
    left_max = max(r.pos_x for r in racks if r.orientation == "E")
    right_min = min(r.pos_x for r in racks if r.orientation == "W")
    assert right_min - left_max > 1  # empty aisle columns between the banks
    by_name = {r.name: r for r in racks}
    assert by_name["R01-C01"].pos_x == left_max and by_name["R02-C01"].pos_x == right_min
    assert by_name["R01-C01"].pos_y == by_name["R02-C01"].pos_y


def test_prod_guards(engine, monkeypatch):
    from app.settings import get_settings
    monkeypatch.setattr(get_settings(), "env", "prod")
    with pytest.raises(SystemExit):
        seed_demo.run(engine, reseed=True)
    created = seed_demo.run(engine)
    assert created["users"] == 0 and created["racks"] == 420
    seed_demo.run(engine, reseed=True, force=True)


def test_cabinets_are_53u_and_old_42u_seed_is_grown(engine):
    seed_demo.run(engine)
    with Session(engine) as s:
        assert {r.u_height for r in s.exec(select(RackRow)).all()} == {53}
        for r in s.exec(select(RackRow)).all():  # simulate a DB seeded before the 53U change
            r.u_height = 42
        s.commit()
    created = seed_demo.run(engine)
    assert created["racks_resized"] == 420 and created["racks"] == 0
    with Session(engine) as s:
        assert {r.u_height for r in s.exec(select(RackRow)).all()} == {53}
    assert seed_demo.run(engine)["racks_resized"] == 0


def test_resize_skipped_when_a_device_would_not_fit(engine):
    seed_demo.run(engine)
    with Session(engine) as s:
        rack = s.exec(select(RackRow).where(RackRow.name == "R01-C01")).one()
        rack.u_height = 60
        s.commit()
        assert not seed_demo._fits(s, rack, 1)  # devices above U1
        assert seed_demo._fits(s, rack, 53)

def test_seed_connections(engine):
    from app.modules.connections.models import ConnectionRow
    from app.modules.connections.service import base_query, connection_out
    first = seed_demo.run(engine)
    assert first["connections"] >= 30
    with Session(engine) as s:
        rows = [connection_out(r) for r in s.exec(base_query()).all()]
        assert len(rows) == first["connections"]
        assert {r["derived_status"] for r in rows} == {"install", "active", "decom"}
        assert {r["cable"]["cable_type"] for r in rows} == {"RJ45", "LC", "DAC"}
        assert any(r["a"]["rack_id"] and r["b"]["rack_id"] and r["a"]["rack_id"] != r["b"]["rack_id"] for r in rows)
    assert seed_demo.run(engine)["connections"] == 0
    assert seed_demo.run(engine, reseed=True)["connections"] == first["connections"]
    with Session(engine) as s:
        assert s.exec(select(func.count()).select_from(ConnectionRow)).one() == first["connections"]


def _assert_item46(engine):
    from app.modules.device_types.lifecycle import readiness_map
    from app.modules.device_types.models import DeviceTypeProfileRow, DeviceTypeRow
    from app.modules.images.models import ProfileImageRow
    with Session(engine) as s:
        types = {t.id: t for t in s.exec(select(DeviceTypeRow)).all()
                 if t.name in seed_demo.ASSET_TYPES}
        assert len(types) == 13
        profs = s.exec(select(DeviceTypeProfileRow).where(DeviceTypeProfileRow.name == "Standard",
                                                          DeviceTypeProfileRow.device_type_id.in_(types))).all()
        assert len(profs) == 13
        ready = readiness_map(s, profs)
        for p in profs:
            assert p.status == "published" and ready[p.id]["ready"], (p.name, ready[p.id])
            assert p.mounting == "rack_19in" and p.weight_kg and p.power_type in ("AC", "DC")
            assert types[p.device_type_id].asset_type == seed_demo.ASSET_TYPES[types[p.device_type_id].name]
        assert sum(p.power_type == "DC" for p in profs) == 1
        assert s.exec(select(func.count()).select_from(ProfileImageRow).where(
            ProfileImageRow.profile_id.in_([p.id for p in profs]), ProfileImageRow.face == "front",
            ProfileImageRow.variant == "original")).one() == 13
        assert s.exec(select(func.count()).select_from(ProfileImageRow).where(
            ProfileImageRow.profile_id.in_([p.id for p in profs]), ProfileImageRow.face == "rear",
            ProfileImageRow.variant == "original")).one() == 13
        by_type = {p.device_type_id: p.id for p in profs}
        demo = s.exec(select(DeviceRow).where(DeviceRow.host_name.in_(seed_demo._demo_host_names()))).all()
        assert demo and all(d.profile_id == by_type[d.device_type_id] for d in demo)
        assert not [d.host_name for d in demo if d.needs_review]
        return len(demo)


def test_item46_profiles_complete_published_with_demo_images(engine, client):
    seed_demo.run(engine)
    n = _assert_item46(engine)
    assert n == len(seed_demo._demo_host_names())
    prof = next(p for p in client.get("/profiles", params={"q": "R660"}).json())
    img = client.get(prof["front_image"]["url"])
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    rack = client.get("/racks", params={"q": "R01-C01"}).json()
    rack = rack[0] if isinstance(rack, list) else rack["items"][0]
    elev = client.get(f"/racks/{rack['id']}/elevation").json()
    assert all(d["effective_front_image"] for d in elev["devices"])


def test_upgrade_from_pre_profile_demo_db(tmp_path, monkeypatch):
    """A demo DB from before p1_15 (types without complete profiles, devices with a type but no profile):
    alembic upgrade head, then a plain re-run upgrades it in place (nothing deleted); --reseed also works."""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    from app.db import make_engine
    from tests.conftest import TEST_DATABASE_URL, reset_postgres
    url = TEST_DATABASE_URL or f"sqlite:///{tmp_path / 'old-demo.db'}"
    if TEST_DATABASE_URL:
        reset_postgres(url)
    monkeypatch.setenv("DCIM_DATABASE_URL", url)
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "p1_14_needs_review")
    eng = make_engine(url)
    (mfr, model, u, full, *_), host = seed_demo.DEVICE_TYPES[0], None
    placed = [(c, h, m, pos, st, face) for c, devs in seed_demo.PLACED.items() for h, m, pos, st, face in devs
              if m == model][:2]
    with eng.begin() as c:
        c.execute(text("INSERT INTO sites(name) VALUES ('Demo DC')"))
        c.execute(text("INSERT INTO halls(site_id, name) VALUES ((SELECT id FROM sites WHERE name='Demo DC'), "
                       "'Demo Hall')"))
        c.execute(text("INSERT INTO device_types(manufacturer, name, u_height, is_full_depth, asset_type) "
                       "VALUES (:m, :n, :u, :f, 'Server')"), {"m": mfr, "n": model, "u": u, "f": full})
        tid = c.execute(text("SELECT id FROM device_types WHERE name=:n"), {"n": model}).scalar()
        # old seed: an incomplete 'Standard' profile (no power_type)
        c.execute(text("INSERT INTO device_type_profiles(device_type_id, name, is_default, u_height, is_full_depth) "
                       "VALUES (:t, 'Standard', true, :u, :f)"), {"t": tid, "u": u, "f": full})
        for cab, h, _, pos, st, face in placed:
            row = cab.split("-")[0]
            c.execute(text("INSERT INTO rows(hall_id, name) SELECT (SELECT id FROM halls WHERE name='Demo Hall'), :r "
                           "WHERE NOT EXISTS (SELECT 1 FROM rows WHERE name=:r2)"), {"r": row, "r2": row})
            c.execute(text("INSERT INTO racks(row_id, name, u_height) SELECT (SELECT id FROM rows WHERE name=:r), "
                           ":c, 42 WHERE NOT EXISTS (SELECT 1 FROM racks WHERE name=:c2)"), {"r": row, "c": cab, "c2": cab})
            c.execute(text("INSERT INTO devices(host_name, status, face, device_type_id, rack_id, position_u) "
                           "VALUES (:h, :s, :f, :t, (SELECT id FROM racks WHERE name=:c), :p)"),
                      {"h": h, "s": st, "f": face, "t": tid, "c": cab, "p": pos})
    command.upgrade(cfg, "head")
    with eng.connect() as c:
        flagged = c.execute(text("SELECT count(*) FROM devices WHERE needs_review_reason='profile_not_published'"))
        assert flagged.scalar() == len(placed)
    before = {h for _, h, *_ in placed}
    first = seed_demo.run(eng, users=False)
    assert first["profiles_completed"] == 1 and first["profiles_published"] == 13 and first["images"] == 26
    n = _assert_item46(eng)
    with Session(eng) as s:
        hosts = set(s.exec(select(DeviceRow.host_name)).all())
    assert before <= hosts and n == len(seed_demo._demo_host_names())  # kept, nothing deleted
    again = seed_demo.run(eng, users=False)
    assert all(v == 0 for v in again.values()), again
    seed_demo.run(eng, reseed=True, users=False)
    _assert_item46(eng)
    eng.dispose()


def test_reseed_adds_rear_to_published_demo_profiles(engine):
    """Upgrade path: demo profiles published before the rear rule get a DEMO rear image and stay published."""
    from sqlmodel import Session, delete, select
    from app.modules.images.models import ProfileImageRow
    from app.modules.device_types.models import DeviceTypeProfileRow
    seed_demo.run(engine, users=False)
    with Session(engine) as s:
        s.exec(delete(ProfileImageRow).where(ProfileImageRow.face == "rear"))
        s.commit()
    again = seed_demo.run(engine, users=False)
    assert again["images"] == 13 and again["profiles_published"] == 0
    with Session(engine) as s:
        profs = s.exec(select(DeviceTypeProfileRow).where(DeviceTypeProfileRow.status == "published")).all()
        assert len(profs) >= 13
    assert seed_demo.run(engine, users=False)["images"] == 0  # idempotent
