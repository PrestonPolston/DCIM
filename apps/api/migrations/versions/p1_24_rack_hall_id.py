"""P1-10 (DESIGN §2.3): racks.hall_id (denormalized from rows.hall_id) + floor-position uniqueness per hall.

- rows: uq_rows_id_hall_id (target of the composite FK).
- racks: hall_id NOT NULL, backfilled from the row; fk_racks_row_id_hall_id_rows (row_id, hall_id) ->
  rows(id, hall_id) ON UPDATE CASCADE (so it can never disagree with the row); partial unique
  uq_racks_hall_id_pos_x_pos_y WHERE deleted_at IS NULL (NULL positions stay free); ix_racks_hall_id_id.
Pre-check: refuses (listing rack ids) if two live racks in one hall share a floor cell. Downgrade drops it all.

Revision ID: p1_24_rack_hall_id
Revises: p1_23_device_ru_slots
"""
import sqlalchemy as sa
from alembic import op

from migrations.p0_common import batch_keep_indexes, precheck

revision = "p1_24_rack_hall_id"
down_revision = "p1_23_device_ru_slots"
branch_labels = None
depends_on = None

LIVE = sa.text("deleted_at IS NULL")


def upgrade() -> None:
    precheck([("live racks sharing a floor cell in one hall",
               "SELECT r.id FROM racks r JOIN rows w ON w.id = r.row_id WHERE r.deleted_at IS NULL "
               "AND r.pos_x IS NOT NULL AND r.pos_y IS NOT NULL AND EXISTS (SELECT 1 FROM racks r2 "
               "JOIN rows w2 ON w2.id = r2.row_id WHERE r2.id <> r.id AND r2.deleted_at IS NULL "
               "AND w2.hall_id = w.hall_id AND r2.pos_x = r.pos_x AND r2.pos_y = r.pos_y)")])
    with batch_keep_indexes("rows") as batch:
        batch.create_unique_constraint("uq_rows_id_hall_id", ["id", "hall_id"])
    with batch_keep_indexes("racks") as batch:
        batch.add_column(sa.Column("hall_id", sa.Integer(), nullable=True))
    op.execute("UPDATE racks SET hall_id = (SELECT rows.hall_id FROM rows WHERE rows.id = racks.row_id)")
    with batch_keep_indexes("racks") as batch:
        batch.alter_column("hall_id", existing_type=sa.Integer(), nullable=False)
        batch.create_foreign_key("fk_racks_row_id_hall_id_rows", "rows", ["row_id", "hall_id"], ["id", "hall_id"],
                                 ondelete="RESTRICT", onupdate="CASCADE")
    op.create_index("uq_racks_hall_id_pos_x_pos_y", "racks", ["hall_id", "pos_x", "pos_y"], unique=True,
                    sqlite_where=LIVE, postgresql_where=LIVE)
    op.create_index("ix_racks_hall_id_id", "racks", ["hall_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_racks_hall_id_id", table_name="racks")
    op.drop_index("uq_racks_hall_id_pos_x_pos_y", table_name="racks")
    with batch_keep_indexes("racks") as batch:
        batch.drop_constraint("fk_racks_row_id_hall_id_rows", type_="foreignkey")
        batch.drop_column("hall_id")
    with batch_keep_indexes("rows") as batch:
        batch.drop_constraint("uq_rows_id_hall_id", type_="unique")
