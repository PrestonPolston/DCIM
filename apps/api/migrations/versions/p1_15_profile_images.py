"""Items 24/31: profile_images (DB blobs; PG STORAGE EXTERNAL, no large objects)

Revision ID: p1_15_profile_images
Revises: p1_14_needs_review
"""
import sqlalchemy as sa
from alembic import op

revision = "p1_15_profile_images"
down_revision = "p1_14_needs_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "profile_images",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
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
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name="pk_profile_images"),
        sa.ForeignKeyConstraint(["profile_id"], ["device_type_profiles.id"],
                                name="fk_profile_images_profile_id_device_type_profiles", ondelete="CASCADE"),
        sa.UniqueConstraint("profile_id", "face", "variant", name="uq_profile_images_profile_id_face_variant"),
        sa.CheckConstraint("face IN ('front','rear')", name="ck_profile_images_face"),
        sa.CheckConstraint("variant IN ('original','thumb')", name="ck_profile_images_variant"),
        sa.CheckConstraint("content_type IN ('image/png','image/jpeg','image/webp')",
                           name="ck_profile_images_content_type"),
        sa.CheckConstraint("byte_size BETWEEN 1 AND 2097152", name="ck_profile_images_byte_size"),
        sa.CheckConstraint("width_px BETWEEN 1 AND 4096 AND height_px BETWEEN 1 AND 4096", name="ck_profile_images_dims"),
        sa.CheckConstraint("length(sha256) = 64", name="ck_profile_images_sha256"),
        sa.CheckConstraint("storage IN ('db','object')", name="ck_profile_images_storage"),
        sa.CheckConstraint("(storage = 'db' AND data IS NOT NULL) OR (storage = 'object' AND object_key IS NOT NULL)",
                           name="ck_profile_images_payload"),
        sa.CheckConstraint("version >= 1", name="ck_profile_images_version"),
    )
    op.create_index("ix_profile_images_sha256", "profile_images", ["sha256"])
    if op.get_bind().dialect.name == "postgresql":  # item 31: images are already compressed
        op.execute("ALTER TABLE profile_images ALTER COLUMN data SET STORAGE EXTERNAL")


def downgrade() -> None:
    op.drop_table("profile_images")
