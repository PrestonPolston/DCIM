"""Cabinet profiles (MIGRATION_SPEC_CABINET_PROFILES.md §1): the cabinet alone, admin-typed, mm only.

New table only; no existing table changes. CHECK names are full names wrapped in op.f() so the naming
convention can't double them (p1_22/p1_27). Downgrade drops the table (data loss: the row count is printed).

Revision ID: p1_28_cabinet_profiles
Revises: p1_27_repair_check_names
"""
import sqlalchemy as sa
from alembic import op

revision = "p1_28_cabinet_profiles"
down_revision = "p1_27_repair_check_names"
branch_labels = None
depends_on = None

T = "cabinet_profiles"
CHECKS = {
    "status": "status IN ('draft','published','retired')",
    "manufacturer_nonempty": "length(trim(manufacturer)) > 0",
    "model_nonempty": "length(trim(model)) > 0",
    "name_nonempty": "length(trim(name)) > 0",
    "version": "version >= 1",
    "u_height": "u_height IS NULL OR u_height BETWEEN 1 AND 100",
    "dims": "(width_mm IS NULL OR width_mm > 0) AND (height_mm IS NULL OR height_mm > 0) AND (depth_mm IS NULL OR "
            "depth_mm > 0)",
    "usable": "(usable_width_mm IS NULL OR (usable_width_mm > 0 AND (width_mm IS NULL OR usable_width_mm <= "
              "width_mm))) AND (usable_depth_mm IS NULL OR (usable_depth_mm > 0 AND (depth_mm IS NULL OR "
              "usable_depth_mm <= depth_mm)))",
    "rack_unit_width": "rack_unit_width IS NULL OR rack_unit_width IN ('19in','23in')",
    "rail_type": "rail_type IS NULL OR rail_type IN ('square_hole','round_hole','threaded')",
    "rail_depth": "(rail_depth_min_mm IS NULL OR rail_depth_min_mm > 0) AND (rail_depth_max_mm IS NULL OR "
                  "rail_depth_max_mm > 0) AND (rail_depth_min_mm IS NULL OR rail_depth_max_mm IS NULL OR "
                  "rail_depth_min_mm <= rail_depth_max_mm) AND (rail_depth_max_mm IS NULL OR depth_mm IS NULL OR "
                  "rail_depth_max_mm <= depth_mm)",
    "front_door": "front_door IS NULL OR front_door IN ('none','perforated','solid','split')",
    "rear_door": "rear_door IS NULL OR rear_door IN ('none','perforated','solid','split')",
    "weight_capacity_kg": "weight_capacity_kg IS NULL OR weight_capacity_kg > 0",
    "color_hex": "color_hex IS NULL OR (length(color_hex) = 7 AND substr(color_hex, 1, 1) = '#')",
    "publish_ready": "status = 'draft' OR (u_height IS NOT NULL AND width_mm IS NOT NULL AND height_mm IS NOT NULL "
                     "AND depth_mm IS NOT NULL AND rack_unit_width IS NOT NULL)",
    "published_at": "status = 'draft' OR published_at IS NOT NULL",
    "retired": "(status = 'retired') = (retired_at IS NOT NULL)",
    "not_self": "supersedes_cabinet_profile_id IS NULL OR supersedes_cabinet_profile_id <> id",
}


def upgrade() -> None:
    ts = sa.DateTime(timezone=True)
    op.create_table(
        T,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("manufacturer", sa.String(128), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("name", sa.String(128), nullable=False, server_default="Standard"),
        sa.Column("status", sa.String(12), nullable=False, server_default="draft"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("supersedes_cabinet_profile_id", sa.Integer()),
        sa.Column("u_height", sa.Integer()),
        sa.Column("width_mm", sa.Integer()),
        sa.Column("height_mm", sa.Integer()),
        sa.Column("depth_mm", sa.Integer()),
        sa.Column("usable_width_mm", sa.Integer()),
        sa.Column("usable_depth_mm", sa.Integer()),
        sa.Column("rack_unit_width", sa.String(8)),
        sa.Column("rail_type", sa.String(16)),
        sa.Column("rail_depth_min_mm", sa.Integer()),
        sa.Column("rail_depth_max_mm", sa.Integer()),
        sa.Column("front_door", sa.String(12)),
        sa.Column("rear_door", sa.String(12)),
        sa.Column("weight_capacity_kg", sa.Numeric(8, 2)),
        sa.Column("color_hex", sa.String(7)),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", ts, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", ts, nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(128)),
        sa.Column("published_at", ts),
        sa.Column("published_by", sa.String(128)),
        sa.Column("retired_at", ts),
        sa.Column("retired_by", sa.String(128)),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cabinet_profiles")),
        sa.ForeignKeyConstraint(["supersedes_cabinet_profile_id"], ["cabinet_profiles.id"], ondelete="RESTRICT",
                                name=op.f("fk_cabinet_profiles_supersedes_id_cabinet_profiles")),
        sa.UniqueConstraint("id", "u_height", name=op.f("uq_cabinet_profiles_id_u_height")),
        *[sa.CheckConstraint(sql, name=op.f(f"ck_{T}_{short}")) for short, sql in CHECKS.items()],
    )
    op.create_index("uq_cabinet_profiles_manufacturer_model_name", T,
                    [sa.text("lower(manufacturer)"), sa.text("lower(model)"), sa.text("lower(name)")], unique=True)
    op.create_index("ix_cabinet_profiles_status", T, ["status"])
    op.create_index("ix_cabinet_profiles_supersedes_cabinet_profile_id", T, ["supersedes_cabinet_profile_id"])


def downgrade() -> None:
    n = op.get_bind().execute(sa.text(f"SELECT count(*) FROM {T}")).scalar()
    print(f"p1_28 downgrade: dropping {T} ({n} rows)")
    op.drop_index("ix_cabinet_profiles_supersedes_cabinet_profile_id", table_name=T)
    op.drop_index("ix_cabinet_profiles_status", table_name=T)
    op.drop_index("uq_cabinet_profiles_manufacturer_model_name", table_name=T)
    op.drop_table(T)
