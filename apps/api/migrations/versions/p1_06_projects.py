"""P1-06: vendors, contacts, projects, project_references, project_contacts + devices.project_id

Revision ID: p1_06_projects
Revises: p1_05_owner
"""
import sqlalchemy as sa
from alembic import op

from migrations.p0_common import batch_keep_indexes, timestamp_cols

revision = "p1_06_projects"
down_revision = "p1_05_owner"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vendors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        *timestamp_cols(),
        sa.PrimaryKeyConstraint("id", name="pk_vendors"),
    )
    op.create_index("uq_vendors_name", "vendors", [sa.text("lower(name)")], unique=True)
    op.create_table(
        "contacts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255)), sa.Column("email", sa.String(255)),
        sa.Column("phone", sa.String(64)), sa.Column("organization", sa.String(255)),
        sa.Column("vendor_id", sa.Integer()),
        *timestamp_cols(),
        sa.PrimaryKeyConstraint("id", name="pk_contacts"),
        sa.ForeignKeyConstraint(["vendor_id"], ["vendors.id"], name="fk_contacts_vendor_id_vendors", ondelete="SET NULL"),
        sa.CheckConstraint("name IS NOT NULL OR email IS NOT NULL", name="ck_contacts_name_or_email"),
    )
    op.create_index("ix_contacts_vendor_id", "contacts", ["vendor_id"])
    op.create_index("uq_contacts_email", "contacts", [sa.text("lower(email)")], unique=True,
                    sqlite_where=sa.text("email IS NOT NULL"), postgresql_where=sa.text("email IS NOT NULL"))
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("site_id", sa.Integer()),
        sa.Column("intake_id", sa.String(64)),
        sa.Column("intake_date", sa.Date()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        *timestamp_cols(),
        sa.PrimaryKeyConstraint("id", name="pk_projects"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], name="fk_projects_site_id_sites", ondelete="RESTRICT"),
    )
    op.create_index("ix_projects_name", "projects", ["name"])
    op.create_index("ix_projects_site_id", "projects", ["site_id"])
    op.create_index("uq_projects_intake_id", "projects", ["intake_id"], unique=True,
                    sqlite_where=sa.text("intake_id IS NOT NULL"), postgresql_where=sa.text("intake_id IS NOT NULL"))
    op.create_table(
        "project_references",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("ref", sa.String(64), nullable=False),
        *timestamp_cols(),
        sa.PrimaryKeyConstraint("id", name="pk_project_references"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_project_references_project_id_projects",
                                ondelete="CASCADE"),
        sa.UniqueConstraint("project_id", "kind", "ref", name="uq_project_references_project_id_kind_ref"),
        sa.CheckConstraint("kind IN ('CHG','DCREQ','INC','OTHER')", name="ck_project_references_kind"),
    )
    op.create_index("ix_project_references_project_id", "project_references", ["project_id"])
    op.create_index("ix_project_references_kind_ref", "project_references", ["kind", "ref"])
    op.create_table(
        "project_contacts",
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("contact_role", sa.String(8), nullable=False),
        sa.Column("title", sa.String(128)),
        sa.PrimaryKeyConstraint("project_id", "contact_id", "contact_role", name="pk_project_contacts"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_project_contacts_project_id_projects",
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], name="fk_project_contacts_contact_id_contacts",
                                ondelete="RESTRICT"),
        sa.CheckConstraint("contact_role IN ('dc','vendor','other')", name="ck_project_contacts_contact_role"),
    )
    with batch_keep_indexes("devices") as batch:
        batch.add_column(sa.Column("project_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_devices_project_id_projects", "projects", ["project_id"], ["id"],
                                 ondelete="SET NULL")
        batch.create_index("ix_devices_project_id", ["project_id"])


def downgrade() -> None:
    with batch_keep_indexes("devices") as batch:
        batch.drop_index("ix_devices_project_id")
        batch.drop_constraint("fk_devices_project_id_projects", type_="foreignkey")
        batch.drop_column("project_id")
    op.drop_table("project_contacts")
    op.drop_table("project_references")
    op.drop_table("projects")
    op.drop_table("contacts")
    op.drop_table("vendors")
