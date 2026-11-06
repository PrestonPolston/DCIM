"""Archive (and optionally purge) audit events older than DCIM_AUDIT_RETENTION_MONTHS.

    python -m app.scripts.audit_archive --out audit-archive.jsonl [--purge]

Rows are written to the JSONL file first; --purge then deletes exactly those rows
(temporarily lifting the append-only guard) and records an `audit.purge` event.
Retention 0 = keep forever (nothing happens). Item 47e: 'restorable' rows (deletion snapshots) use their own
cutoff, max(24, DCIM_RESTORABLE_RETENTION_MONTHS) months (0 = keep them forever), and are never removed by
the 13-month standard purge. The audit.purge event stores the actor
(--actor or the OS user) and the archive SHA-256. Run it under a maintenance DB role: on
Postgres the app role should only have INSERT/SELECT on audit_events.
"""
import argparse
import getpass
import hashlib
import os
import json
import sys
from datetime import timedelta
from pathlib import Path

from sqlalchemy import and_, or_
from sqlmodel import Session, delete, select

import app.models  # noqa: F401
from app.db import engine as default_engine
from app.modules.audit.guards import create_append_only_guards, drop_append_only_guards
from app.modules.audit.models import AuditEventRow
from app.modules.audit.service import record_audit
from app.settings import get_settings
from app.timestamps import utcnow


MIN_RESTORABLE_MONTHS = 24


def run(out: Path, purge: bool, months: int, engine=default_engine, actor: str | None = None,
        restorable_months: int | None = None) -> int:
    actor = actor or getpass.getuser()
    if restorable_months is None:
        restorable_months = get_settings().restorable_retention_months
    if months <= 0:
        print("Retention is 0 (keep forever); nothing to do")
        return 0
    now = utcnow()
    cutoff = now - timedelta(days=30 * months)
    clauses = [and_(AuditEventRow.retention_class == "standard", AuditEventRow.occurred_at < cutoff)]
    r_cutoff = None
    if restorable_months != 0:  # 0 = keep restorable rows forever
        r_cutoff = now - timedelta(days=30 * max(MIN_RESTORABLE_MONTHS, restorable_months))
        clauses.append(and_(AuditEventRow.retention_class == "restorable", AuditEventRow.occurred_at < r_cutoff))
    with Session(engine) as session:
        old = session.exec(select(AuditEventRow).where(or_(*clauses)).order_by(AuditEventRow.id)).all()
        # R-5: archive is owner-only (0600) and fsynced before anything is deleted
        fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as fh:
            for row in old:
                fh.write(json.dumps(row.model_dump(), default=str) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        digest = hashlib.sha256(out.read_bytes()).hexdigest()
        print(f"Archived {len(old)} events older than {cutoff.isoformat()} to {out}")
        if not purge or not old:
            return len(old)
        ids = [r.id for r in old]
        restorable_n = sum(r.retention_class == "restorable" for r in old)
    with engine.begin() as conn:  # one transaction: guard off, delete, guard on, record
        drop_append_only_guards(conn)
        conn.execute(delete(AuditEventRow).where(AuditEventRow.id.in_(ids)))
        create_append_only_guards(conn)
        with Session(bind=conn) as session:
            record_audit(session, None, "audit.purge", "audit_events", None,
                         after={"deleted": len(ids), "before": cutoff.isoformat(),
                                "restorable_before": r_cutoff.isoformat() if r_cutoff else None,
                                "restorable_deleted": restorable_n, "archive": str(out),
                                "archive_sha256": digest, "actor": actor})
            session.flush()
    print(f"Purged {len(ids)} events")
    return len(ids)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--purge", action="store_true")
    parser.add_argument("--actor", help="Who runs the purge (default: OS user); stored on audit.purge")
    args = parser.parse_args(argv)
    run(args.out, args.purge, get_settings().audit_retention_months, actor=args.actor)
    return 0


if __name__ == "__main__":
    sys.exit(main())
