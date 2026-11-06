"""Cabinet profile face images (MIGRATION_SPEC_CABINET_PROFILES.md §2): mirrors profile_images at its p1_22
state (original/thumb/tex + derived_dims), short CHECK names, FK cabinet_profile_id ON DELETE CASCADE.
PG: data column STORAGE EXTERNAL (images are already compressed). Downgrade drops the table (count printed).

Revision ID: p1_29_cabinet_profile_images
Revises: p1_28_cabinet_profiles
"""
import sqlalchemy as sa
from alembic import op

revision = "p1_29_cabinet_profile_images"
down_revision = "p1_28_cabinet_profiles"
branch_labels = None
depends_on = None

T = "cabinet_profile_images"
CHECKS = {
    "face": "face IN ('front','rear')",
    "variant": "variant IN ('original','thumb','tex')",
    "content_type": "content_type IN ('image/png','image/jpeg','image/webp')",
    "byte_size": "byte_size BETWEEN 1 AND 2097152",
    "dims": "width_px BETWEEN 1 AND 4096 AND height_px BETWEEN 1 AND 4096",
    "derived_dims": "variant = 'original' OR (width_px <= 1024 AND height_px <= 1024)",
    "sha256": "length(sha256) = 64",
    "storage": "storage IN ('db','object')",
    "payload": "(storage = 'db' AND data IS NOT NULL) OR (storage = 'object' AND object_key IS NOT NULL)",
    "version": "version >= 1",
}


def upgrade() -> None:
    ts = sa.DateTime(timezone=True)
    op.create_table(
        T,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cabinet_profile_id", sa.Integer(), nullable=False),
        sa.Column("face", sa.String(8), nullable=False),
        sa.Column("variant", sa.String(16), nullable=False, server_default="original"),
        sa.Column("content_type", sa.String(32), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("width_px", sa.Integer(), nullable=False),
        sa.Column("height_px", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage", sa.String(8), nullable=False, server_default="db"),
        sa.Column("data", sa.LargeBinary()),
        sa.Column("object_key", sa.String(512)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("original_filename", sa.String(255)),
        sa.Column("uploaded_by", sa.String(128)),
        sa.Column("created_at", ts, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", ts, nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cabinet_profile_images")),
        sa.ForeignKeyConstraint(["cabinet_profile_id"], ["cabinet_profiles.id"], ondelete="CASCADE",
                                name=op.f("fk_cabinet_profile_images_cabinet_profile_id_cabinet_profiles")),
        sa.UniqueConstraint("cabinet_profile_id", "face", "variant",
                            name=op.f("uq_cabinet_profile_images_cabinet_profile_id_face_variant")),
        *[sa.CheckConstraint(sql, name=op.f(f"ck_{T}_{short}")) for short, sql in CHECKS.items()],
    )
    op.create_index("ix_cabinet_profile_images_sha256", T, ["sha256"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"ALTER TABLE {T} ALTER COLUMN data SET STORAGE EXTERNAL")


def downgrade() -> None:
    n = op.get_bind().execute(sa.text(f"SELECT count(*) FROM {T}")).scalar()
    print(f"p1_29 downgrade: dropping {T} ({n} rows)")
    op.drop_index("ix_cabinet_profile_images_sha256", table_name=T)
    op.drop_table(T)
