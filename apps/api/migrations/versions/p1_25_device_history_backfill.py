"""P1-10 (DESIGN §7 item 12): one device_status_history row for every device that has none.

Rows: from_status NULL, to_status = current status, changed_at = status_changed_at, else created_at,
reason 'p1_25 backfill', under one change_set (source 'migration', note 'p1_25_device_history_backfill').
Devices that already have status history are untouched. Insert-only; downgrade deletes exactly those rows
and that change set.

Revision ID: p1_25_device_history_backfill
Revises: p1_24_rack_hall_id
"""
import sqlalchemy as sa
from alembic import op

revision = "p1_25_device_history_backfill"
down_revision = "p1_24_rack_hall_id"
branch_labels = None
depends_on = None

NOTE = "p1_25_device_history_backfill"
REASON = "p1_25 backfill"


def upgrade() -> None:
    bind = op.get_bind()
    missing = bind.execute(sa.text(
        "SELECT COUNT(*) FROM devices d WHERE NOT EXISTS "
        "(SELECT 1 FROM device_status_history h WHERE h.device_id = d.id)")).scalar()
    if not missing:
        return
    cs = bind.execute(sa.text("INSERT INTO change_sets (source, actor, note) VALUES ('migration', NULL, :n) "
                              "RETURNING id"), {"n": NOTE}).scalar()
    bind.execute(sa.text(
        "INSERT INTO device_status_history (device_id, from_status, to_status, changed_at, changed_by, reason, "
        "change_set_id) SELECT d.id, NULL, d.status, COALESCE(d.status_changed_at, d.created_at), NULL, :r, :cs "
        "FROM devices d WHERE NOT EXISTS (SELECT 1 FROM device_status_history h WHERE h.device_id = d.id)"),
        {"r": REASON, "cs": cs})
    print(f"p1_25: backfilled status history for {missing} device(s) (change_set {cs})")


def downgrade() -> None:
    bind = op.get_bind()
    ids = [r[0] for r in bind.execute(sa.text(
        "SELECT id FROM change_sets WHERE source = 'migration' AND note = :n"), {"n": NOTE}).fetchall()]
    for cs in ids:
        bind.execute(sa.text("DELETE FROM device_status_history WHERE change_set_id = :cs AND reason = :r"),
                     {"cs": cs, "r": REASON})
        bind.execute(sa.text("DELETE FROM change_sets WHERE id = :cs"), {"cs": cs})
