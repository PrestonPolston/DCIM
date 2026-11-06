"""Item 48: restore devices removed by remove_profileless_devices.py from their audit snapshots. OPERATOR ONLY.

    python scripts/restore_from_audit.py --change-set 12 --profile-id 5 [--map 3:7,4:9] [--ids 1,2] --actor you@x
                                          [--execute]     # default is a dry run

Devices come back UNPLACED on a published profile (--profile-id, or --map device_type_id:profile_id), same ids
when free, with their history, ports and the connections whose other end exists. The old location goes in notes.
Refuses with a list (nothing written) on serial conflicts or a missing/unpublished profile mapping.
Same security review as item 47; --execute requires DCIM_ALLOW_PROFILELESS_REMOVAL=1 until cleared.
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session  # noqa: E402

import app.models  # noqa: E402,F401
from app.modules.devices import removal  # noqa: E402

GATE = "DCIM_ALLOW_PROFILELESS_REMOVAL"


def main(argv=None, engine=None, stdin=None, password_reader=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--change-set", type=int, required=True)
    ap.add_argument("--profile-id", type=int)
    ap.add_argument("--map", help="device_type_id:profile_id,...")
    ap.add_argument("--ids")
    ap.add_argument("--actor", required=True)
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--yes", action="store_true", help="Skip the typed confirmation (ignored when DCIM_ENV=prod)")
    args = ap.parse_args(argv)
    if engine is None:
        from app.db import engine
    if args.execute and os.environ.get(GATE) != "1":
        print(f"Refusing --execute: pending DCIM Security guidance (set {GATE}=1 only when cleared)", file=sys.stderr)
        return 3
    import getpass

    from app.settings import get_settings
    try:
        actor = removal.verify_admin(engine, args.actor, (password_reader or getpass.getpass)(
            f"Password for {args.actor}: "))
    except removal.RemovalError as exc:
        print(exc, file=sys.stderr)
        return exc.exit_code
    type_map = dict(tuple(int(x) for x in pair.split(":")) for pair in args.map.split(",")) if args.map else None
    ids = [int(x) for x in args.ids.split(",")] if args.ids else None
    with Session(engine) as session:
        try:
            result = removal.restore(session, change_set_id=args.change_set, actor=actor,
                                     profile_id=args.profile_id, type_map=type_map, ids=ids,
                                     dry_run=True)
            if args.execute:
                n = len(result["restored"])
                expected = f"restore {n} from change_set {args.change_set}"
                if not (args.yes and get_settings().env != "prod"):
                    print(f"Type '{expected}': ", end="", flush=True, file=sys.stderr)
                    if (stdin or sys.stdin).readline().strip() != expected:
                        print("Aborted", file=sys.stderr)
                        return 1
                result = removal.restore(session, change_set_id=args.change_set, actor=actor,
                                         profile_id=args.profile_id, type_map=type_map, ids=ids,
                                         dry_run=False)
                session.commit()
            else:
                session.rollback()
        except removal.RemovalError as exc:
            session.rollback()
            print(f"{exc}" + (f": {json.dumps(exc.details)}" if exc.details else ""), file=sys.stderr)
            return exc.exit_code
    print(json.dumps(result, default=str, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
