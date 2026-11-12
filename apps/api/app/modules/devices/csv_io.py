import csv
import io
import uuid

from sqlalchemy.exc import IntegrityError

from fastapi import Depends, HTTPException, Request
from pydantic import ValidationError
from sqlmodel import Session, select

from app.modules.device_types.models import DeviceTypeRow
from app.modules.devices.models import DeviceRow
from app.modules.devices.schemas import DeviceCreate, ImportResult, ImportRowError
from app.modules.audit.service import record_audit
from app.settings import Settings, get_settings
from app.validation import formula_problem, is_secret_name, neutralize_cell
from app.modules.devices import lifecycle
from app.modules.history.service import new_change_set

MAX_REPORTED_ERRORS = 1000

# Column order for export; import accepts the same headers
# (manufacturer + model resolve device_type_id when it is blank)
CSV_COLUMNS = [
    "id", "host_name", "status", "serial_number", "serial_unavailable", "serial_note", "manufacturer", "model",
    "device_type_id", "profile_id", "orientation", "rack_id", "position_u", "face", "rack",
    "description", "notes", "asset_type", "eos_date", "app_service", "system_type",
    "system_type_confidence", "color_hex", "power_assignment", "historic_name", "owner", "project_intake_id", "created_by",
    "site", "hall", "row", "cabinet", "needs_review", "needs_review_reason",
]
# export-only columns (ignored on import)
READ_ONLY = {"id", "created_by", "site", "hall", "row", "cabinet", "needs_review", "needs_review_reason"}
# header aliases -> canonical column (D7: asset tag and serial are one field)
HEADER_ALIASES = {"asset_tag": "serial_number"}


# Read the raw text/csv body with a hard size cap (enforced while streaming), strict UTF-8
async def read_csv_body(request: Request, settings: Settings = Depends(get_settings)) -> str:
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type != "text/csv":
        raise HTTPException(status_code=415, detail="Send the file with Content-Type: text/csv")
    limit = settings.csv_max_bytes
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise HTTPException(status_code=413, detail=f"CSV is larger than {limit} bytes")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise HTTPException(status_code=413, detail=f"CSV is larger than {limit} bytes")
        chunks.append(chunk)
    raw = b"".join(chunks)
    if b"\x00" in raw:
        raise HTTPException(status_code=422, detail="CSV must not contain NUL bytes")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=422, detail="CSV must be UTF-8 encoded")
    csv.field_size_limit(settings.csv_max_field_chars)
    return text


# Prefix formula-looking text with ' so spreadsheets show it as text (OWASP CSV injection).
# Kept as a name for existing callers; the single rule lives in app.validation.neutralize_cell.
neutralize = neutralize_cell


def export_devices(session: Session, devices: list[DeviceRow]) -> str:
    from app.modules.directory.models import ProjectRow

    types = {t.id: t for t in session.exec(select(DeviceTypeRow)).all()}
    intake = {p.id: p.intake_id for p in session.exec(select(ProjectRow)).all()}
    from app.modules.device_types.models import DeviceTypeProfileRow
    orient = dict(session.exec(select(DeviceTypeProfileRow.id, DeviceTypeProfileRow.orientation)).all())
    from app.modules.locations.models import HallRow, RackRow, RackRowRow, SiteRow
    rack_ids = {d.rack_id for d in devices if d.rack_id}
    where = {}
    if rack_ids:
        for rack, row, hall, site in session.exec(
            select(RackRow, RackRowRow, HallRow, SiteRow)
            .join(RackRowRow, RackRowRow.id == RackRow.row_id).join(HallRow, HallRow.id == RackRowRow.hall_id)
            .join(SiteRow, SiteRow.id == HallRow.site_id).where(RackRow.id.in_(rack_ids))
        ).all():
            where[rack.id] = {"site": site.name, "hall": hall.name, "row": row.name, "cabinet": rack.name}
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    for d in devices:
        t = types.get(d.device_type_id)
        row = d.model_dump()
        row["manufacturer"] = t.manufacturer if t else ""
        row["model"] = t.name if t else ""
        row["project_intake_id"] = intake.get(d.project_id)
        row["orientation"] = orient.get(d.profile_id)
        row.update(where.get(d.rack_id, {}))
        writer.writerow({k: "" if row.get(k) is None else neutralize(row[k]) for k in CSV_COLUMNS})
    return out.getvalue()


CHUNK = 1000


def _clean(raw: dict) -> dict:
    data = {k.strip().lower(): (v or "").strip() for k, v in raw.items() if k}
    return {k: v for k, v in data.items() if v != ""}


# Import devices from CSV. All-or-nothing: rows are checked in order (so rows in
# the same file can conflict with each other) and saved only if every row is valid.
def import_devices(session: Session, text: str, dry_run: bool, max_rows: int = 10_000) -> ImportResult:
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or "host_name" not in [f.strip().lower() for f in reader.fieldnames]:
        raise HTTPException(status_code=422, detail="CSV must have a header row with host_name")

    headers = [f.strip().lower() for f in reader.fieldnames]
    secret = sorted(h for h in headers if is_secret_name(h))
    if secret:  # D10 / R-3: reject the whole file before any row is read
        raise HTTPException(status_code=422, detail={
            "code": "secret_field_not_accepted",
            "message": f"Credentials are not stored in DCIM; remove column(s): {', '.join(secret)}",
        })
    unknown = sorted(set(headers) - set(CSV_COLUMNS) - set(HEADER_ALIASES))
    if unknown:  # item 9: unknown headers are an error (typos would otherwise drop data silently)
        raise HTTPException(status_code=422, detail={
            "code": "unknown_columns", "message": f"Unknown columns: {', '.join(unknown)}", "columns": unknown})
    warnings: list[str] = []
    change_set = new_change_set(session, "csv_import", note="CSV import")
    batch_id = uuid.uuid4().hex
    session.info["import_batch_id"] = batch_id
    errors: list[ImportRowError] = []
    created = 0
    total = 0
    # item 9: preload once (serials incl. soft-deleted, device types); unplaced rows insert in batched chunks
    serials = {s for s in session.exec(select(DeviceRow.serial_number).where(
        DeviceRow.serial_number.is_not(None))).all()}
    type_ids = {(t.manufacturer, t.name): t.id for t in session.exec(select(DeviceTypeRow)).all()}
    from app.modules.device_types.models import DeviceTypeProfileRow as _P
    published: dict[int, list] = {}  # D58: type -> published profiles (orientation variants)
    for pr in session.exec(select(_P).where(_P.status == "published").order_by(_P.id)).all():
        published.setdefault(pr.device_type_id, []).append(pr)
    pending: list[tuple[int, DeviceRow]] = []

    def flush_pending() -> None:
        if not pending:
            return
        try:
            session.flush()
        except IntegrityError as exc:  # should not happen after the in-memory checks; keep all-or-nothing
            session.rollback()
            raise HTTPException(status_code=409, detail={
                "code": "import_conflict", "message": "A database constraint failed in rows "
                f"{pending[0][0]}-{pending[-1][0]}: {str(exc.orig)[:200]}"}) from exc
        for _, dev in pending:
            lifecycle.after_create(session, dev, change_set)
        pending.clear()

    with session.no_autoflush:
        rows = _read_rows(reader, max_rows)
        for line_no, raw in rows:
            total += 1
            formula_cols = [k.strip() for k, v in raw.items() if k and isinstance(v, str) and formula_problem(v)]
            cleaned = _clean(raw)
            details: list[dict] = []

            def err(code: str, message: str, **extra) -> str:
                details.append({"code": code, "message": message, **extra})
                return message
            alias_errors = []
            for alias, canonical in HEADER_ALIASES.items():
                if alias in cleaned:
                    value = cleaned.pop(alias)
                    if canonical in cleaned and cleaned[canonical] != value:
                        alias_errors.append(err("alias_conflict", f"{alias} and {canonical} are the same field and differ"))
                    cleaned.setdefault(canonical, value)
            data = {k: v for k, v in cleaned.items() if k in CSV_COLUMNS and k not in READ_ONLY}
            manufacturer, model = data.pop("manufacturer", None), data.pop("model", None)
            orientation = data.pop("orientation", None)
            intake_id = data.pop("project_intake_id", None)
            if intake_id is not None:
                from app.modules.directory.models import ProjectRow
                project = session.exec(select(ProjectRow.id).where(
                    ProjectRow.intake_id == intake_id, ProjectRow.deleted_at.is_(None))).first()
                if project is None:
                    alias_errors.append(err("unknown_project", f"Unknown project_intake_id '{intake_id}'"))
                else:
                    data["project_id"] = project
            row_errors: list[str] = alias_errors + [
                err("formula_not_allowed", f"{col}: cell starts with = + - @ tab or CR (spreadsheet formula); "
                    "not allowed", column=col)
                for col in formula_cols
            ]
            if formula_cols or alias_errors:
                errors.append(ImportRowError(row=line_no, errors=row_errors, details=details))
                continue
            if "device_type_id" not in data and (manufacturer or model):
                found = type_ids.get((manufacturer, model))
                if found:
                    data["device_type_id"] = found
                else:
                    row_errors.append(err("unknown_device_type", f"Unknown device type '{manufacturer} {model}'"))
            if orientation is not None and orientation not in ("port_front", "power_front"):
                row_errors.append(err("invalid_value", "orientation: must be port_front or power_front",
                                      column="orientation"))
            elif not row_errors and "device_type_id" in data and not data.get("profile_id"):
                try:
                    tid = int(data["device_type_id"])
                except (TypeError, ValueError):
                    tid = None
                variants = published.get(tid, [])
                if orientation:
                    match = [v for v in variants if v.orientation == orientation]
                    if not match:
                        row_errors.append(err("orientation_not_found", f"No published profile of this model has "
                                              f"orientation {orientation}", column="orientation"))
                    else:
                        data["profile_id"] = next((v.id for v in match if v.is_default), match[0].id)
                elif len({v.orientation for v in variants if v.orientation}) >= 2:
                    row_errors.append(err("orientation_required", "This model has published port_front and "
                                          "power_front profiles; set orientation (or profile_id)", column="orientation"))
            elif orientation and data.get("profile_id"):
                try:
                    pr = session.get(_P, int(data["profile_id"]))
                except (TypeError, ValueError):
                    pr = None
                if pr is not None and pr.orientation != orientation:
                    row_errors.append(err("orientation_mismatch", f"profile_id {pr.id} has orientation "
                                          f"{pr.orientation}, not {orientation}", column="orientation"))
            try:
                payload = DeviceCreate(**data)
            except ValidationError as exc:
                row_errors += [err("invalid_value", f"{'.'.join(map(str, e['loc']))}: {e['msg']}",
                                   column=".".join(map(str, e["loc"]))) for e in exc.errors()]
                payload = None
            if payload and not row_errors:
                device = DeviceRow(**payload.model_dump())
                try:
                    if device.serial_number and device.serial_number in serials:
                        raise HTTPException(409, {"code": "serial_conflict", "message":
                                                  f"serial_number '{device.serial_number}' already exists"})
                    placed = device.rack_id is not None
                    if placed:
                        flush_pending()  # placement checks query the DB: earlier rows must be visible
                    lifecycle.create(session, device, change_set, defer=not placed)  # placed: flushes now
                    if not placed:
                        pending.append((line_no, device))
                        if len(pending) >= CHUNK:
                            flush_pending()
                    if device.serial_number:
                        serials.add(device.serial_number)
                    created += 1
                except HTTPException as exc:
                    d = exc.detail if isinstance(exc.detail, dict) else {"code": f"http_{exc.status_code}",
                                                                          "message": str(exc.detail)}
                    details.append(dict(d))
                    row_errors.append(d["message"])
            if row_errors:
                errors.append(ImportRowError(row=line_no, errors=row_errors, details=details))

        if not errors:
            flush_pending()
    session.info.pop("import_batch_id", None)
    if dry_run or errors:
        session.rollback()
    else:
        record_audit(session, None, "device.import.batch", "import", None,
                     after={"rows": total, "created": created}, import_batch_id=batch_id)
        session.commit()
    return ImportResult(
        dry_run=dry_run, total_rows=total, created=created if not errors else 0,
        errors=errors[:MAX_REPORTED_ERRORS], errors_truncated=len(errors) > MAX_REPORTED_ERRORS,
        warnings=warnings,
    )


# Materialize rows with a row cap and csv-level errors mapped to 422
def _read_rows(reader, max_rows: int) -> list[tuple[int, dict]]:
    rows = []
    try:
        for line_no, raw in enumerate(reader, start=2):
            if len(rows) >= max_rows:
                raise HTTPException(status_code=422, detail=f"CSV has more than {max_rows} rows")
            rows.append((line_no, raw))
    except csv.Error as exc:
        raise HTTPException(status_code=422, detail=f"Malformed CSV: {exc}")
    return rows
