"""Item 47: remove every device without a profile (placed, unplaced, soft-deleted). OPERATOR ONLY.

    NOT CLEARED FOR REAL DATA: awaiting DCIM Security guidance on who may run it and on snapshot/export
    access. --execute additionally requires DCIM_ALLOW_PROFILELESS_REMOVAL=1 until then.

    python scripts/remove_profileless_devices.py                       # dry run (default): report + set hash
    python scripts/remove_profileless_devices.py --execute --actor you@example.com --expect-hash <h> \\
        [--include-connections] [--export removed-2026-10-24.json  # file name, written in DCIM_EXPORT_DIR (0700)] [--ids 1,2] [--rack-id 7] [--yes]
        [--backup-confirmed]

--actor must be an ACTIVE admin and re-enters their password; refused actor -> exit 3. --yes skips the typed
confirmations only outside prod. In prod: refuse unless DCIM_BACKUP_MARKER is < 1 h old or --backup-confirmed.

Execute runs in ONE transaction: re-select (FOR UPDATE on PG), hash check, change_set(source='script'),
one audit 'hard_delete' snapshot per device, optional export (0600, JSON + flat CSV) written before commit,
then a real DELETE in FK order. Never run from migrations, app startup or CI against real data.
"""
import argparse
import csv
import hashlib
import time
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session  # noqa: E402

import app.models  # noqa: E402,F401
from app.modules.devices import removal  # noqa: E402
from app.settings import get_settings  # noqa: E402
from app.validation import neutralize_cell  # noqa: E402

GATE = "DCIM_ALLOW_PROFILELESS_REMOVAL"


def _ids(value: str | None):
    return [int(x) for x in value.split(",") if x.strip()] if value else None


def write_export(target: Path):
    def _write(snaps):
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump(snaps, fh, default=str, indent=1)
        flat = target.with_suffix(".csv")
        fd = os.open(flat, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", newline="") as fh:
            cols = ["id", "host_name", "serial_number", "status", "device_type_id", "rack_id", "position_u",
                    "face", "deleted_at"]
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for s in snaps:
                w.writerow({k: neutralize_cell(v) for k, v in s["device"].items()})
        return {"path": str(target.resolve()), "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}
    return _write


def backup_ok(args) -> bool:
    """47c: in prod, a backup marker file (DCIM_BACKUP_MARKER, touched by the backup job) under 1 h old,
    or an explicit --backup-confirmed."""
    if args.backup_confirmed:
        return True
    marker = os.environ.get("DCIM_BACKUP_MARKER")
    return bool(marker) and os.path.isfile(marker) and time.time() - os.path.getmtime(marker) < 3600


def confirm(prompt: str, expected: str, args, stdin) -> bool:
    """Typed confirmation; --yes skips it only outside prod (tests)."""
    if args.yes and get_settings().env != "prod":
        return True
    print(f"{prompt} Type '{expected}': ", end="", flush=True, file=sys.stderr)
    return (stdin or sys.stdin).readline().strip() == expected


def main(argv=None, engine=None, stdin=None, password_reader=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--actor")
    ap.add_argument("--expect-hash")
    ap.add_argument("--include-connections", action="store_true")
    ap.add_argument("--export")
    ap.add_argument("--ids")
    ap.add_argument("--rack-id", type=int)
    ap.add_argument("--yes", action="store_true", help="Skip the typed confirmation (ignored when DCIM_ENV=prod)")
    ap.add_argument("--backup-confirmed", action="store_true",
                    help="prod: a backup was taken (otherwise DCIM_BACKUP_MARKER must be < 1 h old)")
    args = ap.parse_args(argv)
    if engine is None:
        from app.db import engine
    ids = _ids(args.ids)
    with Session(engine) as session:
        devices = removal.select_devices(session, ids, args.rack_id)
        rows = removal.report(session, devices)
        h = removal.set_hash(devices)
        if not args.execute:
            print(json.dumps({"dry_run": True, "count": len(rows), "hash": h, "devices": rows}, default=str, indent=1))
            return 0
    if os.environ.get(GATE) != "1":
        print(f"Refusing --execute: pending DCIM Security guidance (set {GATE}=1 only when cleared)", file=sys.stderr)
        return 3
    if get_settings().env == "prod" and not backup_ok(args):
        print("Refusing: DCIM_ENV=prod and no backup marker under 1 h old (DCIM_BACKUP_MARKER); "
              "take a backup, then pass --backup-confirmed", file=sys.stderr)
        return 3
    target = None
    if args.export:
        from app.modules.devices.export_policy import ExportPolicyError, export_target
        try:
            target = export_target(get_settings().export_dir, args.export)
        except ExportPolicyError as exc:
            print(f"Refusing --export: {exc}", file=sys.stderr)
            return 1
        if target.exists() or target.with_suffix(".csv").exists():
            print(f"Refusing --export: {target} already exists", file=sys.stderr)
            return 1
    if not args.actor or not args.expect_hash:
        print("--execute needs --actor and --expect-hash (from the dry run)", file=sys.stderr)
        return 1
    import getpass
    try:
        actor = removal.verify_admin(engine, args.actor, (password_reader or getpass.getpass)(
            f"Password for {args.actor}: "))
    except removal.RemovalError as exc:
        print(exc, file=sys.stderr)
        return exc.exit_code
    if not confirm(f"Remove {len(rows)} device(s) permanently?", f"remove {len(rows)}", args, stdin):
        print("Aborted", file=sys.stderr)
        return 1
    connected = [r for r in rows if r["ports"] or r["connections"]]
    if args.include_connections and connected:
        for r in connected:
            print(f"  device {r['id']} {r['host_name']}: {r['ports']} port(s), {r['connections']} connection(s)", file=sys.stderr)
        if not confirm("Their ports, connections and cables are deleted too.", "delete connections", args, stdin):
            print("Aborted", file=sys.stderr)
            return 1
    with Session(engine) as session:
        try:
            result = removal.execute(session, actor=actor, expect_hash=args.expect_hash, ids=ids,
                                     rack_id=args.rack_id, include_connections=args.include_connections,
                                     export=write_export(target) if target else None)
            session.commit()
        except removal.RemovalError as exc:
            session.rollback()
            print(f"{exc}" + (f": {exc.details}" if exc.details else ""), file=sys.stderr)
            return exc.exit_code
        except Exception:
            session.rollback()
            raise
    print(json.dumps({"removed": result["removed"], "change_set_id": result["change_set_id"], "hash": h}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
