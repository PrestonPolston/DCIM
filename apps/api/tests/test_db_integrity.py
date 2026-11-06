import sqlite3

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.schema import DEFAULT_NAMING_CONVENTION
from sqlmodel import SQLModel

from app.db import make_engine
from tests.conftest import TEST_DATABASE_URL, reset_postgres

sqlite_only = pytest.mark.skipif(bool(TEST_DATABASE_URL), reason="SQLite-specific (legacy DB / sqlite3 module)")


@sqlite_only
def test_engine_is_dialect_aware():
    engine = make_engine("sqlite://")
    with engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
    # Postgres URL builds without SQLite-only connect args (no connection attempted)
    pytest.importorskip("psycopg")
    make_engine("postgresql+psycopg://u:p@localhost/db")


@pytest.fixture
def migrated(tmp_path, monkeypatch):
    url = TEST_DATABASE_URL or f"sqlite:///{tmp_path / 'm.db'}"
    if TEST_DATABASE_URL:
        reset_postgres(url)
    monkeypatch.setenv("DCIM_DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    return make_engine(url)


def test_constraint_names(migrated):
    insp = inspect(migrated)
    assert {u["name"] for u in insp.get_unique_constraints("halls")} == {"uq_halls_site_id_name"}
    assert {f["name"] for f in insp.get_foreign_keys("devices")} >= {
        "fk_devices_rack_id_racks", "fk_devices_device_type_id_device_types"}
    assert {c["name"] for c in insp.get_check_constraints("devices")} >= {
        "ck_devices_status", "ck_devices_face", "ck_devices_placement", "ck_devices_serial_nonempty"}


@pytest.mark.parametrize("sql", [
    "INSERT INTO devices(host_name, status, face) VALUES ('a', 'bogus', 'front')",
    "INSERT INTO devices(host_name, status, face) VALUES ('a', 'active', 'side')",
    "INSERT INTO devices(host_name, status, face, serial_number) VALUES ('a', 'active', 'front', '  ')",
    "INSERT INTO devices(host_name, status, face, position_u) VALUES ('a', 'active', 'front', 3)",
    "INSERT INTO devices(host_name, status, face) VALUES ('  ', 'active', 'front')",
    "INSERT INTO racks(row_id, hall_id, name, u_height) VALUES (1, 1, 'X', 0)",
    "INSERT INTO racks(row_id, hall_id, name, orientation) VALUES (1, 1, 'X', 'Q')",
    "INSERT INTO racks(row_id, name) VALUES (1, 'X')",  # P1-10: hall_id required
    "INSERT INTO racks(row_id, hall_id, name) VALUES (1, 2, 'X')",  # composite FK: hall must be the row's
    "INSERT INTO racks(row_id, hall_id, name, pos_x, pos_y) VALUES (1, 1, 'X', 0, 0)",  # floor cell taken
    "INSERT INTO device_ru_slots(rack_id, u, side, device_id) VALUES (1, 1, 'front', 1)",  # U already held
    "INSERT INTO device_ru_slots(rack_id, u, side, device_id) VALUES (1, 5, 'top', 1)",
    "INSERT INTO rows(hall_id, name, pos_x) VALUES (1, 'X', -1)",
    "DELETE FROM racks WHERE id = 1",  # FK RESTRICT: a device is mounted
])
def test_raw_bad_writes_rejected(migrated, sql):
    with migrated.begin() as conn:
        conn.execute(text("INSERT INTO sites(name) VALUES ('S')"))
        conn.execute(text("INSERT INTO halls(site_id, name) VALUES (1, 'H')"))
        conn.execute(text("INSERT INTO rows(hall_id, name) VALUES (1, 'R')"))
        conn.execute(text("INSERT INTO halls(site_id, name) VALUES (1, 'H2')"))
        conn.execute(text("INSERT INTO racks(row_id, hall_id, name, pos_x, pos_y) VALUES (1, 1, 'K', 0, 0)"))  # server default 53
        conn.execute(text("INSERT INTO device_types(manufacturer, name) VALUES ('A', 'B')"))
        conn.execute(text("INSERT INTO device_type_profiles(device_type_id, name, u_height) VALUES (1, 'p', 1)"))
        conn.execute(text("INSERT INTO devices(host_name, rack_id, position_u, device_type_id, profile_id) "
                          "VALUES ('h', 1, 1, 1, 1)"))
        conn.execute(text("INSERT INTO device_ru_slots(rack_id, u, side, device_id) VALUES (1, 1, 'front', 1)"))
    with pytest.raises(IntegrityError):
        with migrated.begin() as conn:
            conn.execute(text(sql))


@sqlite_only
def test_migrations_on_legacy_unnamed_db(tmp_path, monkeypatch):
    """A DB created before the naming convention (unnamed constraints) upgrades, downgrades, re-upgrades."""
    db = tmp_path / "legacy.db"
    monkeypatch.setenv("DCIM_DATABASE_URL", f"sqlite:///{db}")
    cfg = Config("alembic.ini")
    nc = dict(SQLModel.metadata.naming_convention)
    monkeypatch.setattr(SQLModel.metadata, "naming_convention", DEFAULT_NAMING_CONVENTION)
    command.upgrade(cfg, "ab5579ca7488")
    monkeypatch.setattr(SQLModel.metadata, "naming_convention", nc)
    c = sqlite3.connect(db)
    c.executescript("""
        INSERT INTO sites(name) VALUES ('S'); INSERT INTO halls(site_id, name) VALUES (1, 'H');
        INSERT INTO rows(hall_id, name) VALUES (1, 'R'); INSERT INTO racks(row_id, name, u_height) VALUES (1, 'K', 42);
        INSERT INTO device_types(manufacturer, name, u_height, is_full_depth) VALUES ('A', 'B', 1, 1);
        INSERT INTO devices(host_name, status, face, rack_id, position_u, device_type_id, serial_number)
            VALUES ('h', 'active', 'front', 1, 1, 1, ' S1 ');
        INSERT INTO devices(host_name, status, face, serial_number) VALUES ('d', 'active', 'front', '');
    """)
    c.commit()
    pre = "p1_17b_profile_versions"
    command.upgrade(cfg, pre)
    assert c.execute("SELECT serial_number FROM devices ORDER BY id").fetchall() == [("S1",), (None,)]
    assert "uq_halls_site_id_name" in c.execute("SELECT sql FROM sqlite_master WHERE name='halls'").fetchone()[0]
    with pytest.raises(RuntimeError, match=r"1 device\(s\) have no profile: 2 \(d\)"):
        command.upgrade(cfg, "head")  # p1_18 refuses and lists the typeless device; nothing changed
    command.downgrade(cfg, "ab5579ca7488")
    command.upgrade(cfg, pre)
    command.downgrade(cfg, "base")


@sqlite_only
def test_precheck_lists_violating_rows(tmp_path, monkeypatch):
    db = tmp_path / "bad.db"
    monkeypatch.setenv("DCIM_DATABASE_URL", f"sqlite:///{db}")
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "p0_02_fk_defaults")
    c = sqlite3.connect(db)
    c.execute("INSERT INTO devices(host_name, status, face) VALUES ('x', 'weird', 'front')")
    c.commit()
    with pytest.raises(RuntimeError, match="ck_devices_status: ids \\[1\\]"):
        command.upgrade(cfg, "head")


def test_migrations_up_down_up(migrated, monkeypatch):
    """Full round trip on whichever DB the suite runs against (SQLite locally, Postgres in CI)."""
    cfg = Config("alembic.ini")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


def test_migration_seeds_one_default_site(migrated):
    with migrated.connect() as conn:
        rows = conn.execute(text("SELECT name FROM sites WHERE is_default")).all()
    assert [r[0] for r in rows] == ["Default"]


def test_rack_default_53_keeps_existing_42u(tmp_path, monkeypatch):
    """Item 23: p1_12 changes only the server default; existing racks/devices are untouched."""
    url = TEST_DATABASE_URL or f"sqlite:///{tmp_path / 'r.db'}"
    if TEST_DATABASE_URL:
        reset_postgres(url)
    monkeypatch.setenv("DCIM_DATABASE_URL", url)
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "p1_11_serial_unavailable")
    eng = make_engine(url)
    with eng.begin() as c:
        c.execute(text("INSERT INTO halls(site_id, name) VALUES ((SELECT min(id) FROM sites), 'H')"))
        c.execute(text("INSERT INTO rows(hall_id, name) VALUES ((SELECT min(id) FROM halls), 'R')"))
        c.execute(text("INSERT INTO racks(row_id, name) VALUES ((SELECT min(id) FROM rows), 'OLD')"))
        c.execute(text("INSERT INTO devices(host_name, rack_id, position_u, status, face) "
                       "VALUES ('d1', (SELECT id FROM racks WHERE name='OLD'), 40, 'active', 'front')"))
    command.upgrade(cfg, "p1_12_rack_default_53")
    with eng.begin() as c:
        assert c.execute(text("SELECT u_height FROM racks WHERE name='OLD'")).scalar() == 42
        assert c.execute(text("SELECT position_u FROM devices WHERE host_name='d1'")).scalar() == 40
        c.execute(text("INSERT INTO racks(row_id, name) VALUES ((SELECT min(id) FROM rows), 'NEW')"))
        assert c.execute(text("SELECT u_height FROM racks WHERE name='NEW'")).scalar() == 53
    command.downgrade(cfg, "p1_11_serial_unavailable")
    with eng.begin() as c:
        c.execute(text("INSERT INTO racks(row_id, name) VALUES ((SELECT min(id) FROM rows), 'DOWN')"))
        assert c.execute(text("SELECT u_height FROM racks WHERE name='DOWN'")).scalar() == 42
        assert c.execute(text("SELECT u_height FROM racks WHERE name='NEW'")).scalar() == 53
    eng.dispose()



def test_p1_16_p1_17_data_steps(tmp_path, monkeypatch):
    """asset_type normalised; PD5: typed devices without a profile linked + flagged; typeless placed flagged;
    existing profiles become drafts; nothing deleted."""
    url = TEST_DATABASE_URL or f"sqlite:///{tmp_path / 'pd5.db'}"
    if TEST_DATABASE_URL:
        reset_postgres(url)
    monkeypatch.setenv("DCIM_DATABASE_URL", url)
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "p1_15_profile_images")
    eng = make_engine(url)
    with eng.begin() as c:
        c.execute(text("INSERT INTO halls(site_id, name) VALUES ((SELECT min(id) FROM sites), 'H')"))
        c.execute(text("INSERT INTO rows(hall_id, name) VALUES ((SELECT min(id) FROM halls), 'R')"))
        c.execute(text("INSERT INTO racks(row_id, name) VALUES ((SELECT min(id) FROM rows), 'K')"))
        c.execute(text("INSERT INTO device_types(manufacturer, name, u_height, is_full_depth, asset_type) "
                       "VALUES ('A', 'T', 1, true, ' Patch Panel '), ('A', 'U', 1, true, 'appliance')"))
        c.execute(text("INSERT INTO device_type_profiles(device_type_id, name, is_default, u_height, is_full_depth) "
                       "VALUES ((SELECT id FROM device_types WHERE name='T'), 'default', true, 1, true)"))
        rack = "(SELECT id FROM racks WHERE name='K')"
        t = "(SELECT id FROM device_types WHERE name='T')"
        c.execute(text(f"INSERT INTO devices(host_name, status, face, device_type_id, rack_id, position_u, asset_type) "
                       f"VALUES ('typed-placed', 'active', 'front', {t}, {rack}, 1, 'Server'), "
                       f"('typed-spare', 'install', 'front', {t}, NULL, NULL, NULL), "
                       f"('bare-placed', 'active', 'front', NULL, {rack}, 3, NULL), "
                       f"('bare-spare', 'install', 'front', NULL, NULL, NULL, NULL)"))
    command.upgrade(cfg, "p1_17_profile_template")
    with eng.begin() as c:
        assert dict(c.execute(text("SELECT name, asset_type FROM device_types")).all()) == {
            "T": "patch_panel", "U": "other"}
        rows = {r[0]: r[1:] for r in c.execute(text(
            "SELECT host_name, profile_id IS NOT NULL, needs_review, needs_review_reason, asset_type FROM devices"))}
        assert rows["typed-placed"] == (True, True, "profile_not_published", "server")
        assert rows["typed-spare"] == (True, True, "profile_not_published", None)
        assert rows["bare-placed"] == (False, True, "placed_without_profile", None)
        assert rows["bare-spare"] == (False, False, None, None)
        assert c.execute(text("SELECT status FROM device_type_profiles")).scalars().all() == ["draft"]
    command.downgrade(cfg, "p1_15_profile_images")
    command.upgrade(cfg, "p1_17b_profile_versions")
    with pytest.raises(RuntimeError, match=r"2 device\(s\) have no profile: \d+ \(bare-placed\), \d+ \(bare-spare\)"):
        command.upgrade(cfg, "head")  # both bare devices have no profile
    with eng.begin() as c:
        c.execute(text("DELETE FROM devices WHERE host_name IN ('bare-spare', 'bare-placed')"))  # what item 47 does
    command.upgrade(cfg, "head")
    with eng.begin() as c:
        with pytest.raises(IntegrityError):
            c.execute(text("INSERT INTO devices(host_name, status, face) VALUES ('x', 'install', 'front')"))
    eng.dispose()


def test_p1_19_marks_snapshots_and_keeps_guards(tmp_path, monkeypatch):
    """Existing hard_delete rows become 'restorable', an audit.migration row is written, and the append-only
    guard still blocks UPDATE/DELETE after upgrade and after downgrade (SQLite triggers re-created)."""
    from sqlalchemy.exc import DBAPIError
    url = TEST_DATABASE_URL or f"sqlite:///{tmp_path / 'p119.db'}"
    if TEST_DATABASE_URL:
        reset_postgres(url)
    monkeypatch.setenv("DCIM_DATABASE_URL", url)
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "p1_17b_profile_versions")
    eng = make_engine(url)
    with eng.begin() as c:
        c.execute(text("INSERT INTO audit_events(action, entity_type, entity_id, before_json) "
                       "VALUES ('hard_delete', 'device', 7, '{}'), ('update', 'device', 7, NULL), "
                       "('device.hard_delete', 'device', 8, '{}')"))

    def blocked():
        for sql in ("UPDATE audit_events SET action = 'x'", "DELETE FROM audit_events"):
            with pytest.raises(DBAPIError, match="append-only"):
                with eng.begin() as c:
                    c.execute(text(sql))
    command.upgrade(cfg, "p1_19_removal_hardening")
    with eng.begin() as c:
        got = dict(c.execute(text("SELECT action, retention_class FROM audit_events")).all())
        assert got == {"hard_delete": "restorable", "update": "standard", "audit.migration": "standard",
                       "device.hard_delete": "restorable"}
        assert c.execute(text("SELECT via FROM audit_events WHERE action='audit.migration'")).scalar() == "migration"
    blocked()
    with pytest.raises(DBAPIError):
        with eng.begin() as c:
            c.execute(text("INSERT INTO audit_events(action, entity_type, retention_class) VALUES ('a','b','forever')"))
    command.downgrade(cfg, "p1_17b_profile_versions")
    blocked()
    command.upgrade(cfg, "head")
    blocked()
    eng.dispose()


def test_p1_20_cable_manager(tmp_path, monkeypatch):
    from sqlalchemy.exc import IntegrityError as IE
    url = TEST_DATABASE_URL or f"sqlite:///{tmp_path / 'p120.db'}"
    if TEST_DATABASE_URL:
        reset_postgres(url)
    monkeypatch.setenv("DCIM_DATABASE_URL", url)
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "p1_18_device_profile_required")
    eng = make_engine(url)
    ins = ("INSERT INTO device_types(manufacturer, name, u_height, is_full_depth, asset_type) "
           "VALUES ('A', :n, 1, true, 'cable_manager')")
    with pytest.raises(IE):
        with eng.begin() as c:
            c.execute(text(ins), {"n": "x"})
    command.upgrade(cfg, "p1_20_asset_type_cable_manager")
    with eng.begin() as c:
        c.execute(text(ins), {"n": "cm"})
    with pytest.raises(IE):
        with eng.begin() as c:
            c.execute(text(ins.replace("cable_manager", "toaster")), {"n": "y"})
    command.downgrade(cfg, "p1_18_device_profile_required")
    with eng.begin() as c:
        assert c.execute(text("SELECT asset_type FROM device_types WHERE name='cm'")).scalar() == "other"
    command.upgrade(cfg, "head")
    eng.dispose()


def test_cable_manager_via_api(client):
    t = client.post("/device-types", json={"manufacturer": "Panduit", "name": "CMPH2", "u_height": 2,
                                           "asset_type": "cable_manager"})
    assert t.status_code == 201 and t.json()["asset_type"] == "cable_manager"


def test_no_doubled_check_names(migrated):
    """p1_22 / p1_27: every CHECK uses the model convention ck_<table>_<name>, never ck_<table>_ck_<table>_."""
    insp = inspect(migrated)
    bad = [(t, c["name"]) for t in insp.get_table_names() for c in insp.get_check_constraints(t)
           if (c.get("name") or "").startswith(f"ck_{t}_ck_")]
    assert not bad, bad


def test_cabinet_profile_migrations_match_spec(migrated):
    """p1_28/p1_29 (MIGRATION_SPEC_CABINET_PROFILES §1.2/§1.3/§2.2): exact names, FK actions, lower() unique."""
    insp = inspect(migrated)
    assert {c["name"] for c in insp.get_check_constraints("cabinet_profiles")} == {f"ck_cabinet_profiles_{n}" for n in (
        "status", "manufacturer_nonempty", "model_nonempty", "name_nonempty", "version", "u_height", "dims", "usable",
        "rack_unit_width", "rail_type", "rail_depth", "front_door", "rear_door", "weight_capacity_kg", "color_hex",
        "publish_ready", "published_at", "retired", "not_self")}
    assert {c["name"] for c in insp.get_check_constraints("cabinet_profile_images")} == {
        f"ck_cabinet_profile_images_{n}" for n in ("face", "variant", "content_type", "byte_size", "dims",
                                                   "derived_dims", "sha256", "storage", "payload", "version")}
    fks = {f["name"]: f for t in ("cabinet_profiles", "cabinet_profile_images") for f in insp.get_foreign_keys(t)}
    sup = "fk_cabinet_profiles_supersedes_id_cabinet_profiles"  # explicit 50-char name, same on SQLite and PG
    assert fks[sup]["options"]["ondelete"] == "RESTRICT"
    assert fks["fk_cabinet_profile_images_cabinet_profile_id_cabinet_profiles"]["options"]["ondelete"] == "CASCADE"
    assert {u["name"] for u in insp.get_unique_constraints("cabinet_profile_images")} == {
        "uq_cabinet_profile_images_cabinet_profile_id_face_variant"}
    assert {u["name"] for u in insp.get_unique_constraints("cabinet_profiles")} == {"uq_cabinet_profiles_id_u_height"}
    with migrated.begin() as conn:
        conn.execute(text("INSERT INTO cabinet_profiles(manufacturer, model, name) VALUES ('Acme','R1','Standard')"))
    with pytest.raises(IntegrityError), migrated.begin() as conn:
        conn.execute(text("INSERT INTO cabinet_profiles(manufacturer, model, name) VALUES ('ACME','r1','standard')"))
    if migrated.dialect.name == "postgresql":
        with migrated.connect() as conn:
            assert conn.execute(text("SELECT attstorage FROM pg_attribute WHERE attrelid = "
                                     "'cabinet_profile_images'::regclass AND attname = 'data'")).scalar() == "e"
