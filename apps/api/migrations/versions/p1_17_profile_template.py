"""Item 38: profile template + lifecycle (status draft/published/retired, mounting, weight_kg)

Schema: existing profiles become drafts (no grandfathering).
Data (PD5, approved; never deletes):
- devices with a device type but no profile (placed or unplaced, incl. soft-deleted) are linked to the
  type's default profile and flagged 'profile_not_published';
- placed devices with no device type are flagged 'placed_without_profile' (still 1U on both faces).

Revision ID: p1_17_profile_template
Revises: p1_16_asset_type_list
"""
import sqlalchemy as sa
from alembic import op

from migrations.p0_common import batch_keep_indexes

revision = "p1_17_profile_template"
down_revision = "p1_16_asset_type_list"
branch_labels = None
depends_on = None

TABLE = "device_type_profiles"


def upgrade() -> None:
    with batch_keep_indexes(TABLE) as batch:
        batch.add_column(sa.Column("status", sa.String(16), nullable=False, server_default="draft"))
        batch.add_column(sa.Column("mounting", sa.String(16)))
        batch.add_column(sa.Column("weight_kg", sa.Numeric()))
        batch.add_column(sa.Column("published_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("retired_at", sa.DateTime(timezone=True)))
        batch.create_check_constraint("status", "status IN ('draft','published','retired')")
        batch.create_check_constraint(
            "mounting", "mounting IS NULL OR mounting IN ('rack_19in','rack_23in','shelf','zero_u','other')")
        batch.create_check_constraint("weight_kg", "weight_kg IS NULL OR (weight_kg > 0 AND weight_kg <= 2000)")
        batch.create_check_constraint("published_at", "status <> 'published' OR published_at IS NOT NULL")
    op.create_index("ix_device_type_profiles_status", TABLE, ["status"])

    conn = op.get_bind()
    d = sa.table("devices", sa.column("id"), sa.column("device_type_id"), sa.column("profile_id"),
                 sa.column("rack_id"), sa.column("needs_review"), sa.column("needs_review_reason"))
    p = sa.table(TABLE, sa.column("id"), sa.column("device_type_id"), sa.column("is_default"))
    default = (sa.select(p.c.id).where(p.c.device_type_id == d.c.device_type_id, p.c.is_default)
               .limit(1).scalar_subquery())
    typed = sa.and_(d.c.device_type_id.is_not(None), d.c.profile_id.is_(None))
    conn.execute(d.update().where(typed).values(profile_id=default, needs_review=True,
                                                needs_review_reason="profile_not_published"))
    conn.execute(d.update().where(d.c.device_type_id.is_(None), d.c.profile_id.is_(None),
                                  d.c.rack_id.is_not(None))
                 .values(needs_review=True, needs_review_reason="placed_without_profile"))


def downgrade() -> None:
    # links/flags from the data step are kept (they are valid pre-p1_17 data too)
    op.drop_index("ix_device_type_profiles_status", table_name=TABLE)
    with batch_keep_indexes(TABLE) as batch:
        for ck in ("published_at", "weight_kg", "mounting", "status"):
            batch.drop_constraint(ck, type_="check")
        for col in ("retired_at", "published_at", "weight_kg", "mounting", "status"):
            batch.drop_column(col)
