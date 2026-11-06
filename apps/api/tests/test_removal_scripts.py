import importlib.util
import io
import json
from pathlib import Path

import pytest
from sqlmodel import Session, func, select

from app.modules.audit.models import AuditEventRow
from app.modules.devices.models import DeviceRow
from app.modules.history.models import ChangeSetRow
from tests.conftest import PASSWORD
from tests.test_locations import dtype, make_rack


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pytestmark = pytest.mark.pre_p1_18  # legacy profile-less rows

_remove = load("remove_profileless_devices")
_restore = load("restore_from_audit")
PW = lambda _prompt: PASSWORD  # noqa: E731


class _Wrap:
    def __init__(self, mod):
        self.mod = mod

    def __getattr__(self, name):
        return getattr(self.mod, name)

    def main(self, argv, **kw):
        kw.setdefault("password_reader", PW)
        if "--execute" in argv and "--yes" not in argv and "stdin" not in kw:
            argv = [*argv, "--yes"]
        return self.mod.main(argv, **kw)


remove, restore = _Wrap(_remove), _Wrap(_restore)


@pytest.fixture
def world(client, engine):
    from datetime import UTC, datetime
    rack = make_rack(client)
    t = dtype(client, 1)
    keeper = client.post("/devices", json={"host_name": "keeper", "device_type_id": t["id"]}).json()
    from tests.test_connections import connect
    with Session(engine) as s:
        rows = [DeviceRow(host_name="bare-placed", rack_id=rack["id"], position_u=9, status="active",
                          serial_number="SER-1", needs_review=True, needs_review_reason="placed_without_profile"),
                DeviceRow(host_name="bare-spare", status="install"),
                DeviceRow(host_name="bare-gone", status="install", deleted_at=datetime.now(UTC))]
        s.add_all(rows)
        s.commit()
        ids = [r.id for r in rows]
    assert connect(client, {"id": ids[0]}, "eth0", keeper, "eth0").status_code == 201
    return {"ids": ids, "keeper": keeper, "rack": rack, "type": t}


def export_env(monkeypatch, tmp_path):
    from app.settings import get_settings
    d = tmp_path / "exports"
    monkeypatch.setenv("DCIM_EXPORT_DIR", str(d))
    get_settings.cache_clear()
    return d


@pytest.fixture(autouse=True)
def _reset_settings():
    from app.settings import get_settings
    yield
    get_settings.cache_clear()


def dry(engine, capsys, *args):
    assert remove.main(list(args), engine=engine) == 0
    return json.loads(capsys.readouterr().out)


def total(engine, model):
    with Session(engine) as s:
        return s.exec(select(func.count()).select_from(model)).one()


def test_dry_run_exact_and_writes_nothing(engine, world, capsys):
    before = (total(engine, DeviceRow), total(engine, AuditEventRow), total(engine, ChangeSetRow))
    r = dry(engine, capsys)
    assert r["dry_run"] and [d["id"] for d in r["devices"]] == world["ids"]
    placed = r["devices"][0]
    assert placed["location"]["rack"] == "R01" and placed["connections"] == 1 and placed["ports"] == 1
    assert r["devices"][1]["location"] == "unplaced" and r["devices"][2]["deleted_at"]
    assert (total(engine, DeviceRow), total(engine, AuditEventRow), total(engine, ChangeSetRow)) == before
    assert dry(engine, capsys, "--ids", str(world["ids"][1]))["count"] == 1


def test_execute_guards(engine, world, capsys, monkeypatch, make_user):
    h = dry(engine, capsys)["hash"]
    make_user("admin", email="ops@example.com")
    base = ["--execute", "--actor", "ops@example.com", "--expect-hash", h, "--yes"]
    assert remove.main(base, engine=engine) == 3  # gate: pending Security guidance
    monkeypatch.setenv(remove.GATE, "1")
    assert remove.main(base, engine=engine) == 2  # connected device without --include-connections
    assert remove.main(["--execute", "--actor", "nobody@x", "--expect-hash", h, "--yes",
                        "--include-connections"], engine=engine) == 3  # unknown actor
    assert remove.main(["--execute", "--actor", "ops@example.com", "--expect-hash", "bad", "--yes",
                        "--include-connections"], engine=engine) == 1
    assert remove.main(["--execute", "--actor", "ops@example.com", "--expect-hash", h,
                        "--include-connections"], engine=engine, stdin=io.StringIO("no\n")) == 1
    capsys.readouterr()
    assert dry(engine, capsys)["count"] == 3  # nothing changed


def test_injected_export_failure_rolls_back(engine, world, capsys, monkeypatch, make_user, tmp_path):
    h = dry(engine, capsys)["hash"]
    make_user("admin", email="ops@example.com")
    monkeypatch.setenv(remove.GATE, "1")
    export_env(monkeypatch, tmp_path)

    def boom(_v):
        raise OSError("disk full")
    monkeypatch.setattr(_remove, "neutralize_cell", boom)  # CSV half of the export fails -> rollback
    with pytest.raises(OSError):
        remove.main(["--execute", "--actor", "ops@example.com", "--expect-hash", h, "--yes",
                     "--include-connections", "--export", "removed.json"], engine=engine)
    capsys.readouterr()
    assert dry(engine, capsys)["count"] == 3
    with Session(engine) as s:
        assert not s.exec(select(AuditEventRow).where(AuditEventRow.action == "hard_delete")).all()


def test_execute_then_restore_round_trip(engine, world, capsys, monkeypatch, make_user, tmp_path, client):
    h = dry(engine, capsys)["hash"]
    make_user("admin", email="ops@example.com")
    monkeypatch.setenv(remove.GATE, "1")
    out = export_env(monkeypatch, tmp_path) / "removed.json"
    assert remove.main(["--execute", "--actor", "ops@example.com", "--expect-hash", h, "--yes",
                        "--include-connections", "--export", "removed.json"], engine=engine) == 0
    res = json.loads(capsys.readouterr().out)
    assert res["removed"] == 3
    assert oct(out.stat().st_mode & 0o777) == "0o600" and out.with_suffix(".csv").exists()
    with Session(engine) as s:
        assert not s.exec(select(DeviceRow).where(DeviceRow.id.in_(world["ids"]))).all()
        events = s.exec(select(AuditEventRow).where(AuditEventRow.action == "hard_delete")).all()
        snaps = [json.loads(e.before_json) for e in events]
        assert len(snaps) == 3 and all(s_["snapshot_version"] == 1 for s_ in snaps)
        assert s.get(ChangeSetRow, res["change_set_id"]).source == "script"
    assert json.loads(out.read_text()) == json.loads(json.dumps(snaps))  # export identical to the snapshots
    assert client.get(f"/devices/{world['keeper']['id']}/connections").json() == []
    # restore: missing mapping refused, nothing written
    cs = str(res["change_set_id"])
    assert restore.main(["--change-set", cs, "--actor", "ops@example.com", "--execute"], engine=engine) == 1
    prof = next(p for p in client.get(f"/device-types/{world['type']['id']}/profiles").json() if p["is_default"])
    assert restore.main(["--change-set", cs, "--actor", "ops@example.com", "--profile-id", str(prof["id"])],
                        engine=engine) == 0  # dry run
    capsys.readouterr()
    with Session(engine) as s:
        assert not s.exec(select(DeviceRow).where(DeviceRow.id.in_(world["ids"]))).all()
    assert restore.main(["--change-set", cs, "--actor", "ops@example.com", "--profile-id", str(prof["id"]),
                         "--execute"], engine=engine) == 0
    restored = json.loads(capsys.readouterr().out)["restored"]
    assert [r["old_id"] for r in restored] == [r["new_id"] for r in restored] == world["ids"]  # same ids
    with Session(engine) as s:
        back = {d.id: d for d in s.exec(select(DeviceRow).where(DeviceRow.id.in_(world["ids"]))).all()}
    assert all(d.rack_id is None and d.profile_id == prof["id"] for d in back.values())
    assert back[world["ids"][0]].serial_number == "SER-1" and "R01 U9" in back[world["ids"][0]].notes
    assert back[world["ids"][2]].deleted_at is not None
    conns = client.get(f"/devices/{world['keeper']['id']}/connections").json()
    assert len(conns) == 1  # connection to the kept device restored
    with Session(engine) as s:
        from app.modules.history.models import RestoredDeviceRow
        rd = s.exec(select(RestoredDeviceRow)).all()
        assert sorted(r.original_device_id for r in rd) == world["ids"]
        assert all(r.restored_device_id == r.original_device_id for r in rd)
        snaps_ev = s.exec(select(AuditEventRow).where(AuditEventRow.action == "hard_delete")).all()
        assert {e.retention_class for e in snaps_ev} == {"restorable"} and {e.via for e in snaps_ev} == {"script"}
        assert all(e.actor_user_id is not None for e in snaps_ev)
        cs_row = s.get(ChangeSetRow, res["change_set_id"])
        assert cs_row.export_path == str(out.resolve()) and len(cs_row.export_sha256) == 64
    # restoring again: already recorded in restored_devices -> refused, nothing written
    assert restore.main(["--change-set", cs, "--actor", "ops@example.com", "--profile-id", str(prof["id"]),
                         "--execute"], engine=engine) == 1


@pytest.mark.parametrize("kind", ["technician", "inactive", "wrong_password", "unknown"])
def test_refused_actor_exits_3(engine, world, capsys, monkeypatch, make_user, kind):
    h = dry(engine, capsys)["hash"]
    monkeypatch.setenv(remove.GATE, "1")
    if kind == "technician":
        make_user("technician", email="ops@example.com")
    elif kind == "inactive":
        make_user("admin", email="ops@example.com", is_active=False)
    elif kind == "wrong_password":
        make_user("admin", email="ops@example.com")
    argv = ["--execute", "--actor", "ops@example.com", "--expect-hash", h, "--yes", "--include-connections"]
    reader = (lambda _p: "wrong-password-xx") if kind == "wrong_password" else PW
    assert _remove.main(argv, engine=engine, password_reader=reader) == 3
    assert _restore.main(["--change-set", "1", "--actor", "ops@example.com", "--execute", "--yes"],
                         engine=engine, password_reader=reader) == 3
    capsys.readouterr()
    assert dry(engine, capsys)["count"] == 3
    if kind == "wrong_password":
        with Session(engine) as s:
            ev = s.exec(select(AuditEventRow).where(AuditEventRow.action == "auth.login_failed", AuditEventRow.via == "script")).all()
            assert ev  # failed re-auth is audited


def test_prod_requires_backup(engine, world, capsys, monkeypatch, make_user, tmp_path):
    import os
    import time
    from app.settings import get_settings
    h = dry(engine, capsys)["hash"]
    make_user("admin", email="ops@example.com")
    monkeypatch.setenv(remove.GATE, "1")
    monkeypatch.setenv("DCIM_ENV", "prod")
    monkeypatch.setenv("DCIM_SECRET_KEY", "k" * 48)
    get_settings.cache_clear()
    try:
        argv = ["--execute", "--actor", "ops@example.com", "--expect-hash", h, "--include-connections"]
        assert _remove.main(argv, engine=engine, password_reader=PW) == 3
        marker = tmp_path / "backup.ok"
        marker.write_text("")
        os.utime(marker, (time.time() - 7200,) * 2)
        monkeypatch.setenv("DCIM_BACKUP_MARKER", str(marker))
        assert _remove.main(argv, engine=engine, password_reader=PW) == 3  # stale marker
        # --yes is ignored in prod: typed confirmation still required
        assert _remove.main([*argv, "--backup-confirmed", "--yes"], engine=engine, password_reader=PW,
                            stdin=io.StringIO("nope\n")) == 1
        marker.touch()
        assert _remove.main(argv, engine=engine, password_reader=PW,
                            stdin=io.StringIO("remove 3\ndelete connections\n")) == 0
    finally:
        monkeypatch.delenv("DCIM_ENV")
        get_settings.cache_clear()


def test_snapshot_keys_are_not_secret(engine, world, capsys, monkeypatch, make_user):
    from app.validation import is_secret_name
    h = dry(engine, capsys)["hash"]
    make_user("admin", email="ops@example.com")
    monkeypatch.setenv(remove.GATE, "1")
    assert remove.main(["--execute", "--actor", "ops@example.com", "--expect-hash", h,
                        "--include-connections"], engine=engine) == 0

    def keys(o):
        if isinstance(o, dict):
            for k, v in o.items():
                yield k
                yield from keys(v)
        elif isinstance(o, list):
            for v in o:
                yield from keys(v)
    with Session(engine) as s:
        for e in s.exec(select(AuditEventRow).where(AuditEventRow.action == "hard_delete")).all():
            assert not [k for k in keys(json.loads(e.before_json)) if is_secret_name(k)]


def test_restore_refuses_hostname_conflict(engine, world, capsys, monkeypatch, make_user, client):
    h = dry(engine, capsys)["hash"]
    make_user("admin", email="ops@example.com")
    monkeypatch.setenv(remove.GATE, "1")
    assert remove.main(["--execute", "--actor", "ops@example.com", "--expect-hash", h,
                        "--include-connections"], engine=engine) == 0
    cs = str(json.loads(capsys.readouterr().out)["change_set_id"])
    assert client.post("/devices", json={"host_name": "BARE-SPARE", "device_type_id": world["type"]["id"]}
                       ).status_code == 201
    prof = next(p for p in client.get(f"/device-types/{world['type']['id']}/profiles").json() if p["is_default"])
    n = total(engine, DeviceRow)
    assert restore.main(["--change-set", cs, "--actor", "ops@example.com", "--profile-id", str(prof["id"]),
                         "--execute"], engine=engine) == 1
    assert "host_name in use" in capsys.readouterr().err
    assert total(engine, DeviceRow) == n  # nothing restored


def test_export_policy(engine, world, capsys, monkeypatch, make_user, tmp_path):
    from app.modules.devices.export_policy import REPO_ROOT, ExportPolicyError, export_dir, export_target
    from app.settings import get_settings
    for bad in (str(REPO_ROOT / "exports"), str(REPO_ROOT / "apps" / "web" / "x"), "/var/www/dcim",
                str(tmp_path / "dist" / "x")):
        with pytest.raises(ExportPolicyError):
            export_dir(bad)
    with pytest.raises(ExportPolicyError):
        export_dir(None)
    loose = tmp_path / "loose"
    loose.mkdir(mode=0o755)
    loose.chmod(0o755)
    with pytest.raises(ExportPolicyError, match="0700"):
        export_dir(str(loose))
    for name in ("../x.json", "sub/x.json", ".hidden", ""):
        with pytest.raises(ExportPolicyError):
            export_target(str(tmp_path / "ok"), name)
    d = export_dir(str(tmp_path / "new"))
    assert oct(d.stat().st_mode & 0o777) == "0o700"
    # the script refuses before touching anything
    h = dry(engine, capsys)["hash"]
    make_user("admin", email="ops@example.com")
    monkeypatch.setenv(remove.GATE, "1")
    monkeypatch.setenv("DCIM_EXPORT_DIR", str(REPO_ROOT / "exports"))
    get_settings.cache_clear()
    assert remove.main(["--execute", "--actor", "ops@example.com", "--expect-hash", h,
                        "--include-connections", "--export", "r.json"], engine=engine) == 1
    capsys.readouterr()
    assert dry(engine, capsys)["count"] == 3 and not (REPO_ROOT / "exports").exists()


def test_export_csv_neutralizes_formulas(engine, client, capsys, monkeypatch, make_user, tmp_path):
    from app.validation import neutralize_cell
    assert neutralize_cell("=HYPERLINK(1)") == "'=HYPERLINK(1)" and neutralize_cell("@x") == "'@x"
    assert neutralize_cell("ok") == "ok" and neutralize_cell(5) == 5
    with Session(engine) as s:
        s.add(DeviceRow(host_name="plain", serial_number="-2+3", status="install"))
        s.commit()
    h = dry(engine, capsys)["hash"]
    make_user("admin", email="ops@example.com")
    monkeypatch.setenv(remove.GATE, "1")
    out = export_env(monkeypatch, tmp_path) / "r.json"
    assert remove.main(["--execute", "--actor", "ops@example.com", "--expect-hash", h, "--export", "r.json"],
                       engine=engine) == 0
    res = json.loads(capsys.readouterr().out)
    text_ = out.with_suffix(".csv").read_text()
    assert "'-2+3" in text_ and oct(out.with_suffix(".csv").stat().st_mode & 0o777) == "0o600"
    import hashlib
    with Session(engine) as s:
        cs = s.get(ChangeSetRow, res["change_set_id"])
        assert cs.export_sha256 == hashlib.sha256(out.read_bytes()).hexdigest()
        run = s.exec(select(AuditEventRow).where(AuditEventRow.action == "device.remove_profileless")).one()
        assert json.loads(run.after_json)["export"]["sha256"] == cs.export_sha256
