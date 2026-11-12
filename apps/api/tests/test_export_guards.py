"""Security guards for spreadsheet output (AUTH_RBAC_PLAN §7; conditions on 2282a2a).

1. Every CSV / XLSX / download writer in apps/api (app/ and scripts/) routes each cell through the shared
   helper app.validation.neutralize_cell() (devices.csv_io.neutralize is the same function). A new writer,
   spreadsheet library or file download outside the allowlist fails here until it is reviewed.
2. formula_allowed_fields (fields exempt from the input formula guard) is pinned to the job-intake notes.
3. neutralize_cell() rules, and the three real exporters neutralise a note-like "=1+1" end to end."""
import ast
import csv
import io
import json
from pathlib import Path

import pytest
from sqlmodel import Session

API_ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = ("app", "scripts")
HELPERS = {"neutralize", "neutralize_cell"}
# Modules allowed to build CSV writers: every writerow() there must wrap its cells in a helper (checked below).
WRITER_MODULES = {"app/modules/devices/csv_io.py", "app/modules/connections/service.py",
                  "scripts/remove_profileless_devices.py"}
# Modules allowed to return a CSV/spreadsheet or attachment download -> the exporter that must produce the body.
DOWNLOAD_MODULES = {"app/modules/devices/router.py": "export_devices",
                    "app/modules/connections/router.py": "export_csv"}
# Binary image bytes served with the stored image's content type (never text/csv, never an attachment).
BINARY_MODULES = {"app/modules/images/router.py", "app/modules/cabinet_profiles/router.py"}
SPREADSHEET_LIBS = {"openpyxl", "xlsxwriter", "xlwt", "xlrd", "pandas", "tablib", "pyexcel", "odf", "ezodf"}
RESPONSES = {"Response", "PlainTextResponse", "StreamingResponse", "FileResponse"}
SPREADSHEET_TYPES = ("csv", "spreadsheet", "excel", "officedocument", "opendocument", "tab-separated")
REVIEW = "route every cell through app.validation.neutralize_cell() and get Security review (AUTH_RBAC_PLAN §7)"


def _name(node):
    return node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else None


def _calls_helper(node):
    return any(isinstance(n, ast.Call) and _name(n.func) in HELPERS for n in ast.walk(node))


def scan(source: str, rel: str) -> list[str]:
    problems = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for m in mods:
                if m.split(".")[0] in SPREADSHEET_LIBS:
                    problems.append(f"{rel}:{node.lineno}: imports {m}; {REVIEW}")
        if not isinstance(node, ast.Call):
            continue
        fn = _name(node.func)
        where = f"{rel}:{node.lineno}"
        if fn in ("writer", "DictWriter") and rel not in WRITER_MODULES:
            problems.append(f"{where}: csv.{fn} outside the allowlisted exporters; {REVIEW}")
        elif fn == "writerows":
            problems.append(f"{where}: writerows() skips per-cell neutralisation; use writerow() with the helper")
        elif fn == "writerow" and not (node.args and _calls_helper(node.args[0])):
            problems.append(f"{where}: writerow() cells are not passed through neutralize_cell(); {REVIEW}")
        elif fn in RESPONSES:
            kw = {k.arg: k.value for k in node.keywords}
            media = kw.get("media_type")
            body = node.args[0] if node.args else kw.get("content")
            attachment = any(isinstance(n, ast.Constant) and isinstance(n.value, str) and "attachment" in n.value
                             for n in ast.walk(node))
            spreadsheet = (isinstance(media, ast.Constant) and isinstance(media.value, str)
                           and any(t in media.value for t in SPREADSHEET_TYPES))
            if fn in ("StreamingResponse", "FileResponse"):
                problems.append(f"{where}: {fn} download is not allowlisted; {REVIEW}")
            elif spreadsheet or attachment:
                exporter = DOWNLOAD_MODULES.get(rel)
                if not (exporter and isinstance(body, ast.Call) and _name(body.func) == exporter):
                    problems.append(f"{where}: CSV/attachment download not built by an allowlisted exporter; {REVIEW}")
            elif media is not None and not isinstance(media, ast.Constant) and rel not in BINARY_MODULES:
                problems.append(f"{where}: Response with a computed media_type is not allowlisted; {REVIEW}")
    return problems


def _sources():
    for d in SCAN_DIRS:
        for p in sorted((API_ROOT / d).rglob("*.py")):
            yield p.relative_to(API_ROOT).as_posix(), p.read_text()


def test_every_writer_and_download_goes_through_neutralize_cell():
    problems = [p for rel, src in _sources() for p in scan(src, rel)]
    assert problems == [], "\n".join(problems)


def test_allowlisted_exporters_really_neutralize():
    """The allowlist is not a free pass: each writer module writes rows, and every row goes through the helper."""
    sources = dict(_sources())
    for rel in WRITER_MODULES:
        tree = ast.parse(sources[rel])
        rows = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and _name(n.func) == "writerow"]
        assert rows and all(_calls_helper(r.args[0]) for r in rows), rel
    for rel, exporter in DOWNLOAD_MODULES.items():
        assert exporter in sources[rel], rel
    from app.modules.devices.csv_io import neutralize
    from app.validation import neutralize_cell
    assert neutralize is neutralize_cell  # one rule for every exporter


@pytest.mark.parametrize("src", [
    "import csv\nw = csv.writer(f)\n",
    "from csv import DictWriter\nw = DictWriter(f, fieldnames=[])\n",
    "w.writerow(row)\n",
    "w.writerow({k: str(v) for k, v in row.items()})\n",
    "w.writerows(rows)\n",
    "import openpyxl\n",
    "from xlsxwriter import Workbook\n",
    "import pandas as pd\n",
    "Response(build(rows), media_type='text/csv')\n",
    "Response(data, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')\n",
    "Response(data, media_type='text/plain', headers={'Content-Disposition': 'attachment; filename=x.txt'})\n",
    "StreamingResponse(gen(), media_type='text/csv')\n",
    "FileResponse(path)\n",
    "Response(content=data, media_type=kind)\n",
])
def test_scanner_flags_bypasses(src):
    assert scan(src, "app/modules/new_feature/router.py"), src


def test_scanner_accepts_the_sanctioned_shapes():
    ok = "w.writerow({k: neutralize_cell(v) for k, v in row.items()})\nResponse(content=b'{}', media_type='application/json')\n"
    assert scan(ok, "app/modules/new_feature/router.py") == []
    assert scan("Response(svc.export_csv(rows), media_type='text/csv')\n", "app/modules/connections/router.py") == []


# ---- 2. formula_allowed_fields pin ----

EXPECTED_FORMULA_ALLOWED = {
    "app.modules.jobs.schemas.JobClose": {"note"},
    "app.modules.jobs.schemas.JobReopen": {"note"},
    "app.modules.jobs.schemas.ItemNote": {"note"},
}


def _all_subclasses(cls):
    for sub in cls.__subclasses__():
        yield sub
        yield from _all_subclasses(sub)


def test_formula_allowed_fields_pinned_to_job_notes():
    import app.main  # noqa: F401  (imports every module, so every InputModel subclass is registered)
    from app.validation import InputModel
    assert InputModel.formula_allowed_fields == frozenset(), (
        "InputModel.formula_allowed_fields must stay empty: exempting a field from the formula guard needs Security review")
    actual = {f"{c.__module__}.{c.__qualname__}": set(c.formula_allowed_fields)
              for c in set(_all_subclasses(InputModel)) if c.formula_allowed_fields}
    assert actual == EXPECTED_FORMULA_ALLOWED, (
        "formula_allowed_fields exempts a field from Security's formula-prefix input guard (AUTH_RBAC_PLAN §7). "
        f"Expected only the job-intake notes {EXPECTED_FORMULA_ALLOWED}, got {actual}. Adding a field or model here "
        "needs Security review first; only then update EXPECTED_FORMULA_ALLOWED in tests/test_export_guards.py.")
    for name in EXPECTED_FORMULA_ALLOWED:
        cls = next(c for c in _all_subclasses(InputModel) if f"{c.__module__}.{c.__qualname__}" == name)
        assert "note" in cls.model_fields, name


# ---- 3. neutralize_cell rules ----

@pytest.mark.parametrize("value", [
    "=1+1", "+1", "-48V", "@SUM(A1)", "\t=1+1", "\tplain", "\rplain", "\r\n=1",
    " =1+1", "   @x", "\n=cmd|' /C calc'!A0", " \t+1", "\u00a0=1+1", "\u3000-1", "\n\n@x",
])
def test_neutralize_cell_prefixes(value):
    from app.validation import neutralize_cell
    assert neutralize_cell(value) == "'" + value


@pytest.mark.parametrize("value", ["ok", "", "   ", "a=1", "rack U12", " plain", "\nplain", "ok\n=1", 5, None, 1.5, True])
def test_neutralize_cell_leaves_safe_values(value):
    from app.validation import neutralize_cell
    assert neutralize_cell(value) == value


# ---- end to end: the three exporters ----

@pytest.mark.pre_p1_18
def test_devices_export_neutralizes_note_like_cells(client, engine):
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO devices(host_name, status, face, notes, description, serial_number) "
                          "VALUES ('dev-1', 'active', 'front', '=1+1', '  @x', ' -2')"))
    row = next(csv.DictReader(io.StringIO(client.get("/devices/export").text)))
    assert (row["notes"], row["description"], row["serial_number"]) == ("'=1+1", "'  @x", "' -2")
    assert row["host_name"] == "dev-1"


def test_connections_export_neutralizes_note_like_cells(client, engine):
    from app.modules.connections.models import ConnectionRow
    from tests.test_connections import connect, dtype, make_rack
    rack = make_rack(client)
    t = dtype(client, 1)
    a = client.post("/devices", json={"host_name": "a-1", "rack_id": rack["id"], "position_u": 10,
                                      "device_type_id": t["id"]}).json()
    b = client.post("/devices", json={"host_name": "b-1", "rack_id": rack["id"], "position_u": 20,
                                      "device_type_id": t["id"]}).json()
    c = connect(client, a, "eth0", b, "eth0", notes="fine")
    assert c.status_code == 201, c.text
    with Session(engine) as s:  # legacy / imported value the input guard never saw
        s.get(ConnectionRow, c.json()["id"]).notes = "=1+1"
        s.commit()
    row = next(csv.DictReader(io.StringIO(client.get("/connections/export").text)))
    assert row["notes"] == "'=1+1" and row["a_host_name"] == "a-1"


@pytest.mark.pre_p1_18  # profileless (legacy) devices are what the removal script removes
def test_removal_script_export_neutralizes_note_like_cells(engine, client, capsys, monkeypatch, make_user, tmp_path):
    from app.modules.devices.models import DeviceRow
    from app.settings import get_settings
    from tests.test_removal_scripts import dry, export_env, remove
    with Session(engine) as s:
        s.add(DeviceRow(host_name="bare-1", serial_number="=1+1", status="install"))
        s.commit()
    try:
        h = dry(engine, capsys)["hash"]
        make_user("admin", email="ops@example.com")
        monkeypatch.setenv(remove.mod.GATE, "1")
        out = export_env(monkeypatch, tmp_path) / "r.json"
        assert remove.main(["--execute", "--actor", "ops@example.com", "--expect-hash", h, "--export", "r.json"],
                           engine=engine) == 0
        json.loads(capsys.readouterr().out)
        row = next(csv.DictReader(io.StringIO(out.with_suffix(".csv").read_text())))
        assert row["serial_number"] == "'=1+1" and row["host_name"] == "bare-1"
    finally:
        get_settings.cache_clear()
