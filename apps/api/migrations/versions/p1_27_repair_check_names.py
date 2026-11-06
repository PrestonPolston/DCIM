"""Repair doubled CHECK names ck_<table>_ck_<table>_<x> -> ck_<table>_<x> (the model naming convention).

Older migrations passed full names through the naming convention, so these CHECKs got the table prefix twice
(p1_22 already fixed profile_images). Same style as p1_22: one batch per table (SQLite: table recreate;
Postgres: drop + recreate the named CHECK). The CHECK expressions are taken from the live schema and are not
changed. Downgrade restores the old doubled names exactly. No data is touched.

Revision ID: p1_27_repair_check_names
Revises: p1_26_placement_history_backfill
"""
import sqlalchemy as sa
from alembic import op

from migrations.p0_common import batch_keep_indexes

revision = "p1_27_repair_check_names"
down_revision = "p1_26_placement_history_backfill"
branch_labels = None
depends_on = None

FIXED = {
    "users": ("role", "auth_source", "email_lower"),
    "change_sets": ("source",),
    "device_status_history": ("to_status",),
    "contacts": ("name_or_email",),
    "project_references": ("kind",),
    "project_contacts": ("contact_role",),
    "device_type_profiles": ("dims", "u_height"),
    "device_ports": ("kind", "role", "lanes", "speed_mbps", "face", "front_map", "not_self", "rear_position"),
    "cables": ("cable_type", "length_m"),
    "connections": ("no_self", "ordered", "port1_lane", "port2_lane"),
}


def _rename(to_doubled: bool) -> None:
    insp = sa.inspect(op.get_bind())
    for table, keys in FIXED.items():
        short, doubled = f"ck_{table}_", f"ck_{table}_ck_{table}_"
        src, dst = (short, doubled) if to_doubled else (doubled, short)
        have = {c["name"]: c["sqltext"] for c in insp.get_check_constraints(table) if c.get("name")}
        todo = [(src + k, dst + k, have[src + k]) for k in keys if src + k in have and dst + k not in have]
        if not todo:
            continue
        with batch_keep_indexes(table) as batch:
            for old, new, sql in todo:
                batch.drop_constraint(op.f(old), type_="check")
                batch.create_check_constraint(op.f(new), sa.text(str(sql)))


def upgrade() -> None:
    _rename(to_doubled=False)


def downgrade() -> None:
    _rename(to_doubled=True)
