"""Baseline device_placement_history row for every currently placed device that has none.

Rows: from_* NULL, to_rack_id/to_position_u/to_face = current placement, changed_by NULL,
reason 'p1_26 backfill', under one change_set (source 'migration', note 'p1_26_placement_history_backfill').
changed_at = the device's updated_at (there is no separate "placed at" column; updated_at is the latest
known time the placement could have been set), falling back to the migration time if NULL.
Idempotent: devices with any placement-history row are skipped. Devices are not modified.
Downgrade deletes only the rows with that reason under that change set, and the change set.

Revision ID: p1_26_placement_history_backfill
Revises: p1_25_device_history_backfill
"""
import sqlalchemy as sa
from alembic import op

revision = "p1_26_placement_history_backfill"
down_revision = "p1_25_device_history_backfill"
branch_labels = None
depends_on = None

NOTE = "p1_26_placement_history_backfill"
REASON = "p1_26 backfill"
MISSING = ("FROM devices d WHERE d.rack_id IS NOT NULL AND d.position_u IS NOT NULL AND NOT EXISTS "
           "(SELECT 1 FROM device_placement_history h WHERE h.device_id = d.id)")


def upgrade() -> None:
    bind = op.get_bind()
    n = bind.execute(sa.text(f"SELECT COUNT(*) {MISSING}")).scalar()
    if not n:
        return
    cs = bind.execute(sa.text("INSERT INTO change_sets (source, actor, note) VALUES ('migration', NULL, :n) "
                              "RETURNING id"), {"n": NOTE}).scalar()
    bind.execute(sa.text(
        "INSERT INTO device_placement_history (device_id, from_rack_id, from_position_u, from_face, to_rack_id, "
        "to_position_u, to_face, reason, changed_at, changed_by, change_set_id) "
        "SELECT d.id, NULL, NULL, NULL, d.rack_id, d.position_u, d.face, :r, "
        f"COALESCE(d.updated_at, CURRENT_TIMESTAMP), NULL, :cs {MISSING}"), {"r": REASON, "cs": cs})
    print(f"p1_26: baseline placement history for {n} device(s) (change_set {cs})")


def downgrade() -> None:
    bind = op.get_bind()
    ids = [r[0] for r in bind.execute(sa.text(
        "SELECT id FROM change_sets WHERE source = 'migration' AND note = :n"), {"n": NOTE}).fetchall()]
    for cs in ids:
        bind.execute(sa.text("DELETE FROM device_placement_history WHERE change_set_id = :cs AND reason = :r"),
                     {"cs": cs, "r": REASON})
        bind.execute(sa.text("DELETE FROM change_sets WHERE id = :cs"), {"cs": cs})
