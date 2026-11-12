"""ePIF (Space & Power) CSV intake onto an existing job: parse -> stage + validate (preview) -> commit.

JOB_INTAKE.md §4-§6, placement-popup.md §7a/§7d, Preston's locked v1 rules (2026-11-12):
- A CSV never creates a job: the batch always belongs to the job typed at step 1.
- Secret / iLO headers reject the whole file (422 import_forbidden_columns, header names only, nothing staged).
- Missing data only warns (D106). Rows that can't legally be written are `held` (request kept, no device).
- Conflicting rows (hostname in that cabinet, serial, RU overlap/out of range, repeated or already-imported ePIF
  ID) are `conflict`: skipped with a reason; the rest of the batch still commits.
- PSU1/PSU2 are staged in epif_psus. device_psu_assignments isn't built yet, so every PSU becomes a fill-later
  item (pdu_missing / psu_unparsed / missing_psu) instead of an assignment (§6, last bullet).
"""
import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass, field

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.modules.audit.service import record_audit
from app.modules.device_types.lifecycle import usable_profile_ids
from app.modules.device_types.models import DeviceTypeProfileRow, DeviceTypeRow
from app.modules.devices import lifecycle
from app.modules.devices.models import DeviceRow
from app.modules.devices.service import validate_placement
from app.modules.directory.models import GroupRow, ProjectRow
from app.modules.history.service import new_change_set
from app.modules.jobs.dcreq import normalize_dcreq
from app.modules.jobs.models import (
    UNRESOLVED, EpifPsuRow, EpifRequestRow, ImportRowRow, JobImportRow, JobOpenItemRow as Item,
)
from app.modules.locations.models import HallRow, RackRow, RackRowRow
from app.timestamps import iso_z, utcnow
from app.validation import formula_problem, is_secret_name, normalise_name

# normalised header -> canonical field (placement-popup.md §7a "Review columns")
ALIASES = {
    "id": "epif_id", "epif_id": "epif_id", "epif": "epif_id",
    "action": "action",
    "name": "name", "host_name": "name", "hostname": "name",
    "manufacturer": "manufacturer", "make": "manufacturer",
    "model": "model",
    "template": "template",
    "managed_by": "managed_by", "managed_by_group": "managed_by",
    "app_service": "app_service",
    "row": "row",
    "rack": "rack", "cabinet": "rack",
    "ru": "ru", "u": "ru", "rack_unit": "ru", "position_u": "ru", "u_position": "ru",
    "airflow": "airflow", "airflow_direction": "airflow",
    "ac_dc": "ac_dc", "acdc": "ac_dc", "power_type": "ac_dc",
    "psu_part": "psu_part", "psu_part_number": "psu_part", "psu_part_no": "psu_part",
    "psu_position": "psu_position",
    "psu1": "psu1", "psu_1": "psu1", "psu2": "psu2", "psu_2": "psu2",
    "s_n": "serial", "sn": "serial", "serial": "serial", "serial_number": "serial",
    "dcreq": "dcreq",
}
_BMC = re.compile(r"(^|_)(i_?lo|idrac|bmc|ipmi)(_|$)")
_PSU = re.compile(r"^\s*([A-Za-z])[\s\-:.]*([0-9]*)\s*$")
POWER = {"AC": "AC", "DC": "DC", "AC/DC": "AC_DC", "AC_DC": "AC_DC", "ACDC": "AC_DC", "AC-DC": "AC_DC"}
PSU_COLUMNS = (("psu1", 1), ("psu2", 2))
ASSUMED_PSU_COUNT = 2  # profiles have no psu_count yet: NULL = assume 2 (JOB_INTAKE.md §6)
FIELD_MAX = {"epif_id": 64, "name": 255, "manufacturer": 255, "model": 255, "template": 255, "managed_by": 255,
             "app_service": 128, "row": 64, "rack": 64, "airflow": 64, "serial": 255, "psu_part": 128,
             "psu_position": 32, "psu1": 64, "psu2": 64}
LEVELS = ("conflict", "held", "warning", "info")


def err(status_code: int, code: str, message: str, **extra) -> HTTPException:
    return HTTPException(status_code, {"code": code, "message": message, **extra})


# ---------------------------------------------------------------- parse
def forbidden_header(h: str) -> bool:
    flat = re.sub(r"[^a-z0-9]+", "_", h.strip().lower()).strip("_")  # no camelCase split: iDRAC -> idrac
    return is_secret_name(h) or bool(_BMC.search(flat) or _BMC.search(normalise_name(h)))


def parse_csv(text: str, max_rows: int, aliases: dict | None = None,
              required: tuple[tuple[str, str], ...] = (("name", "Name"),), what: str = "The ePIF file") \
        -> list[tuple[int, dict]]:
    """Header checks first (nothing is read or stored on a bad header), then rows. Returns [(row_number, cells)]
    with canonical keys; row_number is the 1-based data row. `required` = (canonical, label) columns."""
    aliases = ALIASES if aliases is None else aliases
    try:
        reader = csv.reader(io.StringIO(text))
        header = next(reader, None)
    except csv.Error:
        raise err(422, "malformed_csv", "The file isn't a readable CSV") from None
    if not header or not any(h.strip() for h in header):
        raise err(422, "import_empty", "The file has no header row")
    headers = [h.strip() for h in header]
    bad = [h for h in headers if h and forbidden_header(h)]
    if bad:  # D10: names only, never values; the file is not staged
        raise err(422, "import_forbidden_columns", f"This file has forbidden columns: {', '.join(bad)}. Remove "
                  "those columns and upload again. Secrets are never stored.", headers=bad)
    canon, unknown = [], []
    for h in headers:
        c = aliases.get(normalise_name(h)) if h else None
        if h and c is None:
            unknown.append(h)
        canon.append(c)
    if unknown:
        raise err(422, "unknown_columns", f"Unknown columns: {', '.join(unknown)}", columns=unknown)
    dupes = sorted({c for c in canon if c and canon.count(c) > 1})
    if dupes:
        raise err(422, "duplicate_columns", f"These columns appear more than once: {', '.join(dupes)}",
                  columns=dupes)
    missing = [label for c, label in required if c not in canon]
    if missing:
        raise err(422, "missing_columns", f"{what} needs these columns: {', '.join(missing)}", columns=missing)
    rows = []
    try:
        for values in reader:
            if not any(v.strip() for v in values):
                continue  # blank line
            if len(rows) >= max_rows:
                raise err(422, "too_many_rows", f"The file has more than {max_rows} rows")
            cells = {}
            for c, v in zip(canon, values):
                if c is not None and v.strip():
                    cells[c] = v.strip()
            rows.append((len(rows) + 1, cells))
    except csv.Error:
        raise err(422, "malformed_csv", "The file isn't a readable CSV") from None
    if not rows:
        raise err(422, "import_empty", "The file has no data rows")
    return rows


def parse_psu(raw: str) -> tuple[str, int | None] | None:
    m = _PSU.match(raw)
    if not m:
        return None
    return m.group(1).upper(), (int(m.group(2)) if m.group(2) else None)


# ---------------------------------------------------------------- validate
@dataclass
class RowEval:
    row_number: int
    cells: dict
    messages: list = field(default_factory=list)
    plan: dict = field(default_factory=dict)

    def add(self, level, code, message, field_=None, item_type=None, target_field=None, target=None):
        m = {"code": code, "field": field_, "message": message, "level": level}
        if item_type:
            m["item_type"], m["target_field"] = item_type, target_field
            if target:
                m["target"] = target  # which committed record the item points at (cable_matrix: cable)
        self.messages.append(m)

    @property
    def result(self) -> str:
        levels = {m["level"] for m in self.messages}
        for lvl, res in (("conflict", "conflict"), ("held", "held"), ("warning", "warning")):
            if lvl in levels:
                return res
        return "ready"


class Context:
    """Maps preloaded once per file (JOB_INTAKE.md §5.2)."""

    def __init__(self, session: Session, job: ProjectRow, dcreq: str):
        self.session, self.job, self.dcreq = session, job, dcreq
        self.types = {(t.manufacturer.strip().lower(), t.name.strip().lower()): t
                      for t in session.exec(select(DeviceTypeRow)).all()}
        defaults = session.exec(select(DeviceTypeProfileRow).where(DeviceTypeProfileRow.is_default.is_(True))).all()
        self.default_profile = {p.device_type_id: p for p in defaults}
        self.usable = usable_profile_ids(session, defaults)
        stmt = (select(RackRow, RackRowRow.name, HallRow.name).join(RackRowRow, RackRowRow.id == RackRow.row_id)
                .join(HallRow, HallRow.id == RackRow.hall_id).where(RackRow.deleted_at.is_(None)))
        if job.site_id is not None:
            stmt = stmt.where(HallRow.site_id == job.site_id)
        self.racks: dict[tuple[str, str], list] = {}
        for rack, row_name, hall_name in session.exec(stmt).all():
            self.racks.setdefault((row_name.strip().lower(), rack.name.strip().lower()), []).append((rack, hall_name))
        self.serials = set(session.exec(select(DeviceRow.serial_number).where(DeviceRow.serial_number.is_not(None))).all())
        self.done_ids = set(session.exec(select(EpifRequestRow.external_id).where(
            EpifRequestRow.external_id.is_not(None))).all())
        self.groups = {g.name.lower(): g.id for g in session.exec(select(GroupRow)).all()}
        # in-file tracking
        self.seen_ids: dict[str, int] = {}
        self.seen_serials: dict[str, int] = {}
        self.seen_hosts: dict[tuple[int, str], int] = {}
        self.spans: dict[int, list] = {}


def evaluate(ctx: Context, row_number: int, cells: dict) -> RowEval:
    ev = RowEval(row_number, cells)
    for k, v in cells.items():
        if formula_problem(v):
            ev.add("warning", "formula_text", f"{k} starts like a spreadsheet formula; stored as text", k)
        if k in FIELD_MAX and len(v) > FIELD_MAX[k]:
            cells[k] = v[:FIELD_MAX[k]]
            ev.add("warning", "value_truncated", f"{k} is longer than {FIELD_MAX[k]} characters; it was cut", k)
    p = ev.plan
    p.update(host=cells.get("name"), manufacturer=cells.get("manufacturer"), model=cells.get("model"),
             template=cells.get("template"), managed_by=cells.get("managed_by"), app_service=cells.get("app_service"),
             row=cells.get("row"), rack=cells.get("rack"), airflow=cells.get("airflow"), serial=cells.get("serial"),
             psu_part=cells.get("psu_part"), psu_position=cells.get("psu_position"))

    # ePIF ID (K1: digits, usually 5; warn only). Repeated in the file or already imported = conflict.
    ext = cells.get("epif_id")
    p["external_id"] = ext
    if ext is None:
        ev.add("warning", "epif_id_missing", "No ePIF ID on this row", "epif_id")
    else:
        if not ext.isdigit():
            ev.add("warning", "epif_id_format", "The ePIF ID should be digits only", "epif_id", "other", "epif_id")
        elif len(ext) != 5:
            ev.add("info", "epif_id_length", "ePIF IDs are usually 5 digits", "epif_id")
        if ext in ctx.seen_ids:
            ev.add("conflict", "duplicate_epif_id", f"ePIF ID {ext} is repeated in this file (row "
                   f"{ctx.seen_ids[ext]})", "epif_id", "other", "epif_id")
        elif ext in ctx.done_ids:
            ev.add("conflict", "epif_id_already_imported", f"ePIF ID {ext} was already imported", "epif_id",
                   "other", "epif_id")
        ctx.seen_ids.setdefault(ext, row_number)

    # DCREQ column: informational (the batch belongs to the typed job)
    if cells.get("dcreq"):
        norm = normalize_dcreq(cells["dcreq"])
        if norm is None:
            ev.add("warning", "dcreq_format", "The DCREQ in this row isn't a valid DCREQ; the job's DCREQ is used",
                   "dcreq")
        elif norm != ctx.dcreq:
            ev.add("warning", "dcreq_mismatch", f"The row says {norm}; it is imported onto {ctx.dcreq}", "dcreq")

    # Action
    action = (cells.get("action") or "").strip().lower()
    if not action:
        action = "install"
        ev.add("info", "action_defaulted", "No action given; treated as Install", "action")
    p["action"] = action if action in ("install", "remove") else None
    if action == "remove":
        ev.add("held", "remove_not_applied", "Remove rows aren't applied by job intake v1; decommission the device "
               "from its page", "action", "other", "action")
    elif action != "install":
        ev.add("held", "action_unknown", "Action must be Install or Remove", "action", "other", "action")

    # Power type
    pt = None
    if cells.get("ac_dc"):
        pt = POWER.get(cells["ac_dc"].strip().upper().replace(" ", ""))
        if pt is None:
            ev.add("warning", "power_type_unknown", "AC/DC must be AC, DC or AC/DC", "ac_dc", "other", "power_type")
    p["power_type"] = pt

    # Managed by: existing group by name (the text is kept either way)
    p["group_id"] = ctx.groups.get(cells["managed_by"].lower()) if cells.get("managed_by") else None

    # PSU1/PSU2: staged; no assignment table yet, so each becomes a fill-later item
    psus = []
    for col, idx in PSU_COLUMNS:
        raw = cells.get(col)
        if raw is None:
            if idx <= ASSUMED_PSU_COUNT:
                ev.add("warning", "missing_psu", f"PSU{idx} is empty", col, "missing_psu", f"psu_{idx}")
            continue
        parsed = parse_psu(raw)
        if parsed is None:
            psus.append((idx, raw, None, None))
            ev.add("warning", "psu_unparsed", f"Can't read PSU{idx} value '{raw}'", col, "psu_unparsed", f"psu_{idx}")
            continue
        feed, port = parsed
        psus.append((idx, raw, feed, port))
        where = f"feed {feed}" + (f", port {port}" if port is not None else ", no port")
        ev.add("warning", "psu_not_assigned", f"PSU{idx} {raw} ({where}) is staged; PDU assignments aren't "
               "available yet", col, "pdu_missing", f"psu_{idx}")
    p["psus"] = psus

    if p["action"] != "install":
        return ev
    # ---- Install: what's needed for a device to exist (placement rule §0a + D36 profile)
    host = p["host"]
    if not host:
        ev.add("held", "missing_hostname", "Name is required for an Install row", "name", "missing_hostname",
               "host_name")
    dtype = None
    if p["manufacturer"] and p["model"]:
        dtype = ctx.types.get((p["manufacturer"].lower(), p["model"].lower()))
    if dtype is None:
        ev.add("held", "missing_profile", "No device type matches Manufacturer + Model; ask an admin for a profile",
               "model", "missing_profile", "profile_id")
    else:
        prof = ctx.default_profile.get(dtype.id)
        if prof is None or prof.id not in ctx.usable:
            ev.add("held", "profile_not_usable", f"{dtype.manufacturer} {dtype.name} has no usable published default "
                   "profile; ask an admin", "model", "profile_not_usable", "profile_id")
        else:
            p["profile"] = prof
        p["device_type_id"] = dtype.id
    if pt and p.get("profile") is not None and p["profile"].power_type and p["profile"].power_type != pt:
        ev.add("warning", "power_type_mismatch", f"ePIF says {pt}, profile is {p['profile'].power_type}", "ac_dc",
               "other", "power_type")

    rack = None
    if not p["row"] or not p["rack"]:
        ev.add("held", "missing_cabinet", "Row and Rack are needed to place the device", "rack", "missing_position",
               "rack_id")
    else:
        found = ctx.racks.get((p["row"].lower(), p["rack"].lower()), [])
        if len(found) == 1:
            rack = found[0][0]
        elif not found:
            ev.add("held", "unresolved_cabinet", f"No cabinet '{p['rack']}' in row '{p['row']}'", "rack",
                   "unresolved_cabinet", "rack_id")
        else:
            halls = ", ".join(sorted(h for _, h in found))
            ev.add("held", "ambiguous_cabinet", f"'{p['rack']}' in row '{p['row']}' exists in several halls ({halls})",
                   "rack", "unresolved_cabinet", "rack_id")
    p["rack_id"] = rack.id if rack else None
    ru_raw = cells.get("ru")
    ru = int(ru_raw) if ru_raw and ru_raw.isdigit() and int(ru_raw) >= 1 else None
    if ru is None:
        ev.add("held", "missing_position", "RU is missing" if not ru_raw else "RU must be a whole number from 1",
               "ru", "missing_position", "position_u")
    p["position_u"] = ru

    # Serial: optional (warn), unique
    serial = p["serial"]
    if serial is None:
        ev.add("warning", "missing_serial", "No S/N", "serial", "missing_serial", "serial_number")
    elif serial in ctx.serials:
        ev.add("conflict", "serial_conflict", f"S/N {serial} is already on another device", "serial", "other",
               "serial_number")
    elif serial in ctx.seen_serials:
        ev.add("conflict", "serial_conflict", f"S/N {serial} is repeated in this file (row "
               f"{ctx.seen_serials[serial]})", "serial", "other", "serial_number")
    if serial:
        ctx.seen_serials.setdefault(serial, row_number)

    # Placement against the DB (existing rule) and against earlier rows of this file
    prof = p.get("profile")
    if rack is not None and ru is not None and host and prof is not None:
        key = (rack.id, host.lower())
        if key in ctx.seen_hosts:
            ev.add("conflict", "hostname_conflict", f"Host name '{host}' is repeated for cabinet '{rack.name}' in this "
                   f"file (row {ctx.seen_hosts[key]})", "name", "other", "host_name")
        top = ru + prof.u_height - 1
        for lo, hi, face, full, other_row in ctx.spans.get(rack.id, []):
            if ru <= hi and lo <= top and (face == "front" or full or prof.is_full_depth):
                ev.add("conflict", "ru_overlap", f"U{ru}-U{top} overlaps row {other_row} of this file in cabinet "
                       f"'{rack.name}'", "ru", "other", "position_u")
                break
        probe = DeviceRow(host_name=host, status="install", device_type_id=dtype.id, profile_id=prof.id,
                          rack_id=rack.id, position_u=ru, face="front", project_id=ctx.job.id)
        code = placement_problem(ctx.session, probe)
        if code:
            ev.add(*code)
        if ev.result != "conflict":
            ctx.seen_hosts.setdefault(key, row_number)
            ctx.spans.setdefault(rack.id, []).append((ru, top, "front", prof.is_full_depth, row_number))
    return ev


def placement_problem(session: Session, probe: DeviceRow):
    """Run the existing placement validation (fit, overlap, hostname per cabinet, profile) on a probe device and
    map its errors to (level, code, message, field, item_type, target_field)."""
    try:
        with session.no_autoflush:
            validate_placement(session, probe, require=True)
    except HTTPException as exc:
        return classify(exc)
    return None


def classify(exc: HTTPException):
    d = exc.detail
    code = d.get("code") if isinstance(d, dict) else None
    msg = d.get("message") if isinstance(d, dict) else str(d)
    if code == "hostname_conflict":
        return ("conflict", "hostname_conflict", msg, "name", "other", "host_name")
    if code == "serial_conflict":
        return ("conflict", "serial_conflict", msg, "serial", "other", "serial_number")
    if code and code.startswith("profile"):
        return ("held", "profile_not_usable", msg, "model", "profile_not_usable", "profile_id")
    if "does not fit" in msg:
        return ("conflict", "ru_out_of_range", msg, "ru", "other", "position_u")
    if "overlaps" in msg:
        return ("conflict", "ru_overlap", msg, "ru", "other", "position_u")
    return ("conflict", code or "placement_rejected", msg, "ru", "other", "position_u")


def evaluate_all(session: Session, job: ProjectRow, dcreq: str, rows: list[tuple[int, dict]]) -> list[RowEval]:
    ctx = Context(session, job, dcreq)
    return [evaluate(ctx, n, dict(cells)) for n, cells in rows]


# ---------------------------------------------------------------- output
def counts(rows: list[ImportRowRow]) -> dict:
    c = {k: 0 for k in ("ready", "warning", "held", "conflict", "committed", "skipped")}
    for r in rows:
        c[r.result] += 1
    return {"total": len(rows), **c}


def public_messages(raw: str | None) -> list[dict]:
    return [{k: m.get(k) for k in ("code", "field", "message", "level", "item_type", "target_field", "target")}
            for m in json.loads(raw or "[]")]


def _end_text(cells: dict, side: str) -> str | None:
    host, port, slot = cells.get(f"{side}_name"), cells.get(f"{side}_port"), cells.get(f"{side}_slot")
    if not host and not port:
        return None
    return f"{host or '?'}:{slot + '/' if slot else ''}{port or '?'}"


def row_out(r: ImportRowRow, kind: str = "epif") -> dict:
    cells = json.loads(r.raw_json)
    base = {"id": r.id, "row_number": r.row_number, "result": r.result, "messages": public_messages(r.messages_json),
            "cells": cells, "device_id": r.device_id, "epif_request_id": r.epif_request_id,
            "connection_id": r.connection_id, "cable_id": r.cable_id}
    if kind == "cable_matrix":
        return {**base, "epif_id": None, "matrix_id": cells.get("matrix_id"), "action": cells.get("action"),
                "hostname": cells.get("a_name"), "row": cells.get("a_row"), "rack": cells.get("a_rack"),
                "ru": cells.get("a_ru"), "a": _end_text(cells, "a"), "z": _end_text(cells, "z"),
                "trail": cells.get("trail"), "cable_label": cells.get("cable_label")}
    return {**base, "epif_id": cells.get("epif_id"), "matrix_id": None, "action": cells.get("action"),
            "hostname": cells.get("name"), "row": cells.get("row"), "rack": cells.get("rack"), "ru": cells.get("ru"),
            "a": None, "z": None, "trail": None, "cable_label": None}


def import_out(session: Session, imp: JobImportRow, with_rows: bool = True, reupload: str | None = None) -> dict:
    rows = session.exec(select(ImportRowRow).where(ImportRowRow.job_import_id == imp.id)
                        .order_by(ImportRowRow.row_number)).all()
    out = {"id": imp.id, "job_id": imp.project_id, "dcreq": imp.dcreq, "kind": imp.kind, "filename": imp.filename,
           "sha256": imp.sha256, "status": imp.status, "uploaded_at": iso_z(imp.uploaded_at),
           "uploaded_by": imp.uploaded_by, "change_set_id": imp.change_set_id, "counts": counts(rows),
           "reupload": reupload}
    if with_rows:
        out["rows"] = [row_out(r, imp.kind) for r in rows]
    return out


# ---------------------------------------------------------------- stage
def actor(session: Session) -> str | None:
    return getattr(session.info.get("user"), "email", None)


def _write_rows(session: Session, imp: JobImportRow, evals: list[RowEval]) -> None:
    for ev in evals:
        session.add(ImportRowRow(job_import_id=imp.id, row_number=ev.row_number, raw_json=json.dumps(ev.cells),
                                 result=ev.result, messages_json=json.dumps(ev.messages)))


def stage(session: Session, job: ProjectRow, dcreq: str, ref_id: int, kind: str, text: str, filename: str | None,
          max_rows: int) -> tuple[JobImportRow, str | None]:
    """Returns (batch, reupload) where reupload is None (new batch), 'review' or 'committed'."""
    if kind == "cable_matrix":
        from app.modules.jobs import cable_matrix as kind_mod
    else:
        kind_mod = None
    parse = kind_mod.parse if kind_mod else parse_csv
    run = kind_mod.evaluate_all if kind_mod else evaluate_all
    rows = parse(text, max_rows)  # 422s happen here, before anything is stored
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    same = session.exec(select(JobImportRow).where(JobImportRow.project_id == job.id, JobImportRow.kind == kind,
                                                   JobImportRow.sha256 == sha)
                        .order_by(JobImportRow.id.desc())).first()
    if same is not None and same.status == "committed":
        return same, "committed"  # idempotent: nothing new is staged
    evals = run(session, job, dcreq, rows)
    cs = new_change_set(session, "csv_import", note=f"job {job.id} {kind} stage")
    if same is not None:  # same file again, not committed: re-validate the same batch (latest DB state)
        for r in session.exec(select(ImportRowRow).where(ImportRowRow.job_import_id == same.id)).all():
            session.delete(r)
        session.flush()
        same.status, same.filename = "review", filename or same.filename
        same.uploaded_at, same.uploaded_by = utcnow(), actor(session)
        imp, reupload = same, "review"
    else:
        imp = JobImportRow(project_id=job.id, dcreq=dcreq, dcreq_reference_id=ref_id, kind=kind,
                           filename=filename, sha256=sha, uploaded_by=actor(session), uploaded_at=utcnow())
        reupload = None
    session.add(imp)
    session.flush()
    _write_rows(session, imp, evals)
    record_audit(session, None, "job_import.stage", "job_import", imp.id, after={
        "job_id": job.id, "kind": kind, "filename": filename, "sha256": sha, "rows": len(evals),
        "reupload": reupload, "change_set_id": cs.id})
    session.commit()
    session.refresh(imp)
    return imp, reupload


def abandon(session: Session, imp: JobImportRow) -> None:
    if imp.status != "review":
        raise err(409, "import_not_in_review", f"This import is {imp.status}", status=imp.status)
    cs = new_change_set(session, "csv_import", note=f"job_import {imp.id} abandon")
    imp.status = "abandoned"
    session.add(imp)
    record_audit(session, None, "job_import.abandon", "job_import", imp.id, after={"change_set_id": cs.id})
    session.commit()


# ---------------------------------------------------------------- commit
def upsert_item(session: Session, job_id: int, item_type: str, source: str, change_set_id: int, *,
                target: dict, target_field: str | None, note: str | None, import_row_id: int | None,
                who: str | None) -> tuple[Item, bool]:
    """One unresolved item per job + type + target + field (dedupe). Re-raising refreshes note + staging row."""
    stmt = select(Item).where(Item.project_id == job_id, Item.item_type == item_type, Item.status.in_(UNRESOLVED),
                              func.coalesce(Item.target_field, "") == (target_field or ""))
    for col in ("epif_request_id", "device_id", "connection_id", "cable_id"):
        v = target.get(col)
        stmt = stmt.where(getattr(Item, col) == v if v is not None else getattr(Item, col).is_(None))
    if not target:
        stmt = stmt.where(Item.import_row_id == import_row_id)
    with session.no_autoflush:
        found = session.exec(stmt).first()
    if found is not None:
        found.note, found.import_row_id = note, import_row_id
        session.add(found)
        return found, False
    item = Item(project_id=job_id, item_type=item_type, source=source, target_field=target_field, note=note,
                import_row_id=import_row_id, created_by=who, change_set_id=change_set_id, **target)
    session.add(item)
    session.flush()
    record_audit(session, None, "job_open_item.create", "job_open_item", item.id, after={
        "job_id": job_id, "item_type": item_type, "target_field": target_field, **target,
        "import_row_id": import_row_id, "change_set_id": change_set_id})
    return item, True


def _items_for(session, job_id, ev_messages, cs_id, target, row_id, who, created, source="epif", targets=None):
    """One item per message that names an item_type. `targets` maps a message's 'target' key (e.g. 'cable')
    to a different target dict than the default."""
    for m in ev_messages:
        if m.get("item_type"):
            tgt = (targets or {}).get(m.get("target"), target)
            item, new = upsert_item(session, job_id, m["item_type"], source, cs_id, target=tgt,
                                    target_field=m.get("target_field"), note=m["message"], import_row_id=row_id,
                                    who=who)
            if new:
                created.append(item)


def _request(session, job, imp, dcreq, ref_id, p, device_id=None) -> EpifRequestRow:
    prof = p.get("profile")
    req = EpifRequestRow(
        project_id=job.id, job_import_id=imp.id, external_id=p.get("external_id"), action=p.get("action"),
        status="done" if device_id else "open", requested_host_name=p.get("host"),
        manufacturer_text=p.get("manufacturer"), model_text=p.get("model"), template_text=p.get("template"),
        device_type_id=p.get("device_type_id"), profile_id=prof.id if prof is not None else None,
        managed_by_group_id=p.get("group_id"), managed_by_text=p.get("managed_by"), app_service=p.get("app_service"),
        rack_id=p.get("rack_id"), row_text=p.get("row"), rack_text=p.get("rack"), position_u=p.get("position_u"),
        airflow_text=p.get("airflow"), power_type=p.get("power_type"), serial_number=p.get("serial"),
        dcreq=dcreq, dcreq_reference_id=ref_id, device_id=device_id, completed_at=utcnow() if device_id else None)
    session.add(req)
    session.flush()
    for idx, raw, feed, port in p.get("psus", []):
        session.add(EpifPsuRow(epif_request_id=req.id, psu_index=idx, raw_value=raw, pdu_feed=feed, pdu_port=port,
                               part_number=p.get("psu_part"), position=p.get("psu_position"), source="csv"))
    return req


def _create_device(session: Session, job: ProjectRow, p: dict, cs) -> tuple[DeviceRow | None, tuple | None]:
    """Create through the normal device lifecycle in a savepoint; a rejection is returned as a conflict."""
    prof = p["profile"]
    dev = DeviceRow(host_name=p["host"], status="install", device_type_id=p["device_type_id"], profile_id=prof.id,
                    rack_id=p["rack_id"], position_u=p["position_u"], face="front", serial_number=p.get("serial"),
                    app_service=p.get("app_service"), project_id=job.id)
    sp = session.begin_nested()
    try:
        lifecycle.create(session, dev, cs, defer=True)
        session.flush()
        lifecycle.after_create(session, dev, cs)
        session.flush()
        sp.commit()
        return dev, None
    except HTTPException as exc:
        sp.rollback()
        return None, classify(exc)
    except IntegrityError:
        sp.rollback()
        return None, ("conflict", "write_conflict", "The database refused this row (serial, host name or rack "
                      "units taken at the same time)", "name", "other", "host_name")


@dataclass
class CommitAcc:
    committed: list = field(default_factory=list)
    held: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    created: list = field(default_factory=list)

    def count(self, which: str, import_id: int) -> int:
        return sum(1 for x in getattr(self, which) if x["import_id"] == import_id)

    def warn(self, ev: "RowEval", imp: JobImportRow, hostname: str | None) -> None:
        for m in ev.messages:
            if m["level"] == "warning":
                self.warnings.append({"code": m["code"], "message": m["message"], "field": m["field"],
                                      "item_type": m.get("item_type"), "target_field": m.get("target_field"),
                                      "import_id": imp.id, "row_number": ev.row_number, "hostname": hostname})


def reasons(ev: "RowEval", level: str) -> list[dict]:
    return [m for m in public_messages(json.dumps(ev.messages)) if m["level"] == level]


def _commit_epif(session: Session, job: ProjectRow, dcreq: str, ref_id: int, imp: JobImportRow, rows: list,
                 cs, who: str | None, acc: CommitAcc) -> None:
    # re-validate against the DB as it is now (it may have changed since the preview)
    evals = evaluate_all(session, job, dcreq, [(r.row_number, json.loads(r.raw_json)) for r in rows])
    for r, ev in zip(rows, evals):
        p, res = ev.plan, ev.result
        if res in ("ready", "warning"):
            dev, problem = _create_device(session, job, p, cs)
            if problem:
                ev.add(*problem)
                res = "conflict"
        base = {"import_id": imp.id, "kind": imp.kind, "row_number": r.row_number, "epif_id": p.get("external_id"),
                "hostname": p.get("host")}
        if res == "conflict":
            r.result = "skipped"
            acc.skipped.append({**base, "reasons": reasons(ev, "conflict")})
            _items_for(session, job.id, [m for m in ev.messages if m["level"] == "conflict"], cs.id, {}, r.id,
                       who, acc.created)
        elif res == "held":
            req = _request(session, job, imp, dcreq, ref_id, p)
            r.result, r.epif_request_id = "held", req.id
            acc.held.append({**base, "epif_request_id": req.id, "reasons": reasons(ev, "held")})
            _items_for(session, job.id, ev.messages, cs.id, {"epif_request_id": req.id}, r.id, who, acc.created)
        else:
            req = _request(session, job, imp, dcreq, ref_id, p, device_id=dev.id)
            r.result, r.epif_request_id, r.device_id = "committed", req.id, dev.id
            acc.committed.append({**base, "device_id": dev.id, "epif_request_id": req.id})
            _items_for(session, job.id, ev.messages, cs.id, {"device_id": dev.id}, r.id, who, acc.created)
        if res != "conflict":
            acc.warn(ev, imp, p.get("host"))
        r.messages_json = json.dumps(ev.messages)
        session.add(r)


def commit_batches(session: Session, job: ProjectRow, dcreq: str, ref_id: int, imports: list[JobImportRow]) -> dict:
    """All-or-nothing for the writable rows of every batch given, in ONE change set. Held rows keep their request
    / staging row and items; conflict rows are skipped with reasons; the batch still commits (200, never 4xx for
    data). Batches commit oldest first, so an ePIF batch creates devices before a cable batch connects them."""
    who = actor(session)
    cs = new_change_set(session, "csv_import", note=f"job {job.id} commit imports {[i.id for i in imports]}")
    acc = CommitAcc()
    for imp in sorted(imports, key=lambda i: (i.kind != "epif", i.id)):
        session.info["import_batch_id"] = f"job_import:{imp.id}"
        rows = session.exec(select(ImportRowRow).where(ImportRowRow.job_import_id == imp.id)
                            .order_by(ImportRowRow.row_number)).all()
        if imp.kind == "cable_matrix":
            from app.modules.jobs import cable_matrix
            cable_matrix.commit_rows(session, job, dcreq, imp, rows, cs, who, acc)
        else:
            _commit_epif(session, job, dcreq, ref_id, imp, rows, cs, who, acc)
        imp.status, imp.change_set_id = "committed", cs.id
        session.add(imp)
        record_audit(session, None, "job_import.commit", "job_import", imp.id, after={
            "job_id": job.id, "kind": imp.kind, "committed": acc.count("committed", imp.id),
            "held": acc.count("held", imp.id), "skipped": acc.count("skipped", imp.id), "change_set_id": cs.id})
    session.info.pop("import_batch_id", None)
    resolved = resolve_not_uploaded(session, job.id, {i.kind for i in imports}, cs.id, who)
    session.commit()
    return {"committed": acc.committed, "held": acc.held, "skipped": acc.skipped, "warnings": acc.warnings,
            "open_items_created": [i.id for i in acc.created], "resolved_item_ids": resolved}


NOT_UPLOADED = {"epif": "epif_not_uploaded", "cable_matrix": "cable_matrix_not_uploaded"}


def resolve_not_uploaded(session: Session, job_id: int, kinds: set[str], cs_id: int, who: str | None) -> list[int]:
    """Spec §3: the skip-file item is auto-resolved when that kind of file is committed on the job."""
    types = [NOT_UPLOADED[k] for k in kinds]
    items = session.exec(select(Item).where(Item.project_id == job_id, Item.item_type.in_(types),
                                            Item.status.in_(UNRESOLVED))).all()
    now = utcnow()
    for i in items:
        i.status, i.resolved_at, i.resolved_by, i.deferred_at, i.deferred_by = "resolved", now, who, None, None
        session.add(i)
        record_audit(session, None, "job_open_item.resolve", "job_open_item", i.id, after={
            "status": "resolved", "auto": True, "change_set_id": cs_id})
    return [i.id for i in items]
