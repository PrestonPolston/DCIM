"""P1-10 (DESIGN §2.4 option 1): device_ru_slots, PK (rack_id, u, side) = DB-level no-overlap; backfilled.

One row per U per side a racked device blocks (full depth = both sides, else its face; 0 U = none), from its
profile's u_height / is_full_depth. Maintained by app.modules.devices.slots (after_flush hook). The backfill
refuses to run (listing device ids) if existing placements overlap. Downgrade drops the derived table only.

Revision ID: p1_23_device_ru_slots
Revises: p1_22_profile_image_tex
"""
import sqlalchemy as sa
from alembic import op

revision = "p1_23_device_ru_slots"
down_revision = "p1_22_profile_image_tex"
branch_labels = None
depends_on = None


def upgrade() -> None:
    slots = op.create_table(
        "device_ru_slots",
        sa.Column("rack_id", sa.Integer(), nullable=False),
        sa.Column("u", sa.Integer(), nullable=False),
        sa.Column("side", sa.String(5), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("rack_id", "u", "side", name="pk_device_ru_slots"),
        sa.ForeignKeyConstraint(["rack_id"], ["racks.id"], name="fk_device_ru_slots_rack_id_racks", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], name="fk_device_ru_slots_device_id_devices",
                                ondelete="CASCADE"),
        sa.CheckConstraint("side IN ('front','rear')", name=op.f("ck_device_ru_slots_side")),
        sa.CheckConstraint("u >= 1", name=op.f("ck_device_ru_slots_u")),
    )
    op.create_index("ix_device_ru_slots_device_id", "device_ru_slots", ["device_id"])
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT d.id, d.rack_id, d.position_u, d.face, p.u_height, p.is_full_depth FROM devices d "
        "LEFT JOIN device_type_profiles p ON p.id = d.profile_id "
        "WHERE d.rack_id IS NOT NULL AND d.position_u IS NOT NULL ORDER BY d.id")).fetchall()
    taken, out, clash = {}, [], []
    for did, rack, pos, face, h, fd in rows:
        h, fd = (1, True) if h is None else (h, bool(fd))
        for u in range(pos, pos + h):
            for side in (("front", "rear") if fd else (face or "front",)):
                key = (rack, u, side)
                if key in taken:
                    clash.append((taken[key], did, rack, u, side))
                    continue
                taken[key] = did
                out.append({"rack_id": rack, "u": u, "side": side, "device_id": did})
    if clash:
        raise RuntimeError("Fix overlapping placements before migrating (device, device, rack, U, side):\n  "
                           + "\n  ".join(map(str, clash[:50])))
    if out:
        op.bulk_insert(slots, out)


def downgrade() -> None:
    op.drop_index("ix_device_ru_slots_device_id", table_name="device_ru_slots")
    op.drop_table("device_ru_slots")
