"""P1-01: default site (sites.is_default, at most one) + seed 'Default'

Revision ID: p1_01_default_site
Revises: p0_08_auth_audit
"""
import sqlalchemy as sa
from alembic import op

from migrations.p0_common import NC

revision = "p1_01_default_site"
down_revision = "p0_08_auth_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("sites", naming_convention=NC) as batch:
        batch.add_column(sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_index("uq_sites_default", "sites", ["is_default"], unique=True,
                    sqlite_where=sa.text("is_default"), postgresql_where=sa.text("is_default"))
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT count(*) FROM sites WHERE is_default")).scalar():
        return
    # reuse an existing site literally named 'Default', otherwise create it
    if bind.execute(sa.text("SELECT count(*) FROM sites WHERE name = 'Default'")).scalar():
        bind.execute(sa.text("UPDATE sites SET is_default = true WHERE name = 'Default'"))
    else:
        bind.execute(sa.text("INSERT INTO sites (name, is_default) VALUES ('Default', true)"))


def downgrade() -> None:
    # the seeded site stays (it may have halls); only the flag goes
    op.drop_index("uq_sites_default", table_name="sites")
    with op.batch_alter_table("sites", naming_convention=NC) as batch:
        batch.drop_column("is_default")
