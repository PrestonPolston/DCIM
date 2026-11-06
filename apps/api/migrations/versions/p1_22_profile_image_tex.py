"""D51: profile_images 'tex' variant (1024 px WebP for 3D textures).

ck_profile_images_variant gains 'tex'; new ck_profile_images_derived_dims keeps derived variants <= 1024 px.
The 2 MiB byte_size and 4096 px dims CHECKs already cover tex and stay as they are. SQLite: batch recreate;
Postgres: drop/recreate the named CHECKs.
Also repairs p1_15's doubled CHECK names (ck_profile_images_ck_profile_images_<x>, created through the naming
convention) to the model's ck_profile_images_<x>; downgrade restores the p1_15 names exactly.
No data is touched on upgrade; existing originals get their tex via
scripts/regenerate_image_variants.py (idempotent). Downgrade removes only tex rows (derived, regenerable).

Revision ID: p1_22_profile_image_tex
Revises: p1_21_profile_orientation
"""
import sqlalchemy as sa
from alembic import op

from migrations.p0_common import batch_keep_indexes

revision = "p1_22_profile_image_tex"
down_revision = "p1_21_profile_orientation"
branch_labels = None
depends_on = None

CHECKS = {
    "face": "face IN ('front','rear')",
    "content_type": "content_type IN ('image/png','image/jpeg','image/webp')",
    "byte_size": "byte_size BETWEEN 1 AND 2097152",
    "dims": "width_px BETWEEN 1 AND 4096 AND height_px BETWEEN 1 AND 4096",
    "sha256": "length(sha256) = 64",
    "storage": "storage IN ('db','object')",
    "payload": "(storage = 'db' AND data IS NOT NULL) OR (storage = 'object' AND object_key IS NOT NULL)",
    "version": "version >= 1",
}
OLD_VARIANT = "variant IN ('original','thumb')"
NEW_VARIANT = "variant IN ('original','thumb','tex')"
DERIVED_DIMS = "variant = 'original' OR (width_px <= 1024 AND height_px <= 1024)"
DOUBLED = "ck_profile_images_ck_profile_images_"
SHORT = "ck_profile_images_"


def _existing() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_check_constraints("profile_images") if c.get("name")}


def _rewrite(from_prefix: str, to_prefix: str, variant: str, derived: bool) -> None:
    have = _existing()
    with batch_keep_indexes("profile_images") as batch:
        for key in [*CHECKS, "variant", "derived_dims"]:
            for prefix in {from_prefix, to_prefix}:
                if prefix + key in have:
                    batch.drop_constraint(op.f(prefix + key), type_="check")
        for key, text in CHECKS.items():
            batch.create_check_constraint(op.f(to_prefix + key), text)
        batch.create_check_constraint(op.f(to_prefix + "variant"), variant)
        if derived:
            batch.create_check_constraint(op.f(SHORT + "derived_dims"), DERIVED_DIMS)


def upgrade() -> None:
    _rewrite(DOUBLED, SHORT, NEW_VARIANT, derived=True)


def downgrade() -> None:
    n = op.get_bind().execute(sa.text("DELETE FROM profile_images WHERE variant = 'tex'")).rowcount
    if n:
        print(f"p1_22 downgrade: removed {n} derived tex row(s) (regenerate after re-upgrading)")
    _rewrite(SHORT, DOUBLED, OLD_VARIANT, derived=False)
