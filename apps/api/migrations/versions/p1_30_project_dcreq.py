"""Job intake (JOB_INTAKE.md §2, §2.1, §9.1): a job is a projects row keyed by its primary DCREQ.

- project_references: ck_project_references_dcreq_format (kind <> 'DCREQ' OR the D73 format) and
  uq_project_references_dcreq (ref) WHERE kind = 'DCREQ' (each DCREQ on one project).
  The format CHECK is one portable expression (length/substr/IN), identical on SQLite and Postgres.
- projects: status ('open'|'closed'), opened_at NOT NULL (backfilled from created_at; never rewritten),
  created_by, closed_at, closed_by, primary_dcreq_id FK project_references ON DELETE RESTRICT (unique when set),
  ck_projects_status, ck_projects_closed, ix_projects_current_opened_at, ix_projects_recently_closed.
Precheck (no silent rewrite): refuses if a DCREQ reference is not already canonical (trim + upper + format),
or if one DCREQ is on two projects. Existing projects become status 'open' with no primary DCREQ (not jobs).
Downgrade drops it all (job status/close data is lost).

Revision ID: p1_30_project_dcreq
Revises: p1_29_cabinet_profile_images
"""
import sqlalchemy as sa
from alembic import op

from migrations.p0_common import batch_keep_indexes, precheck

revision = "p1_30_project_dcreq"
down_revision = "p1_29_cabinet_profile_images"
branch_labels = None
depends_on = None

_DIGITS = "('0','1','2','3','4','5','6','7','8','9')"


def dcreq_sql(col: str) -> str:  # frozen copy of app.modules.jobs.dcreq.dcreq_sql
    digits = " AND ".join(f"substr({col}, {i}, 1) IN {_DIGITS}" for i in range(9, 13))
    return f"length({col}) = 12 AND substr({col}, 1, 8) = 'DCREQ000' AND {digits}"


CURRENT = sa.text("status = 'open' AND deleted_at IS NULL")
RECENT = sa.text("status = 'closed' AND deleted_at IS NULL")
HAS_PRIMARY = sa.text("primary_dcreq_id IS NOT NULL")
IS_DCREQ = sa.text("kind = 'DCREQ'")


def upgrade() -> None:
    precheck([
        ("DCREQ references not in the canonical DCREQ000NNNN form (fix by hand; trim/uppercase are not applied)",
         f"SELECT id FROM project_references WHERE kind = 'DCREQ' AND NOT ({dcreq_sql('ref')})"),
        ("DCREQ references on more than one project",
         "SELECT r.id FROM project_references r WHERE r.kind = 'DCREQ' AND EXISTS (SELECT 1 FROM "
         "project_references r2 WHERE r2.kind = 'DCREQ' AND r2.ref = r.ref AND r2.id <> r.id)"),
    ])
    with batch_keep_indexes("project_references") as batch:
        batch.create_check_constraint(op.f("ck_project_references_dcreq_format"),
                                      f"kind <> 'DCREQ' OR ({dcreq_sql('ref')})")
    op.create_index("uq_project_references_dcreq", "project_references", ["ref"], unique=True,
                    sqlite_where=IS_DCREQ, postgresql_where=IS_DCREQ)

    with batch_keep_indexes("projects") as batch:
        batch.add_column(sa.Column("status", sa.String(12), nullable=False, server_default="open"))
        batch.add_column(sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("created_by", sa.String(128)))
        batch.add_column(sa.Column("closed_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("closed_by", sa.String(128)))
        batch.add_column(sa.Column("primary_dcreq_id", sa.Integer()))
    op.execute("UPDATE projects SET opened_at = created_at WHERE opened_at IS NULL")
    with batch_keep_indexes("projects") as batch:
        batch.alter_column("opened_at", existing_type=sa.DateTime(timezone=True), nullable=False,
                           server_default=sa.func.now())
        batch.create_foreign_key("fk_projects_primary_dcreq_id_project_references", "project_references",
                                 ["primary_dcreq_id"], ["id"], ondelete="RESTRICT")
        batch.create_check_constraint(op.f("ck_projects_status"), "status IN ('open','closed')")
        batch.create_check_constraint(op.f("ck_projects_closed"), "(status = 'closed') = (closed_at IS NOT NULL)")
    op.create_index("uq_projects_primary_dcreq_id", "projects", ["primary_dcreq_id"], unique=True,
                    sqlite_where=HAS_PRIMARY, postgresql_where=HAS_PRIMARY)
    op.create_index("ix_projects_current_opened_at", "projects", ["opened_at"],
                    sqlite_where=CURRENT, postgresql_where=CURRENT)
    op.create_index("ix_projects_recently_closed", "projects", ["closed_at"],
                    sqlite_where=RECENT, postgresql_where=RECENT)


def downgrade() -> None:
    n = op.get_bind().execute(sa.text("SELECT count(*) FROM projects WHERE primary_dcreq_id IS NOT NULL")).scalar()
    print(f"p1_30 downgrade: {n} jobs lose status/opened/closed data (projects and references are kept)")
    op.drop_index("ix_projects_recently_closed", table_name="projects")
    op.drop_index("ix_projects_current_opened_at", table_name="projects")
    op.drop_index("uq_projects_primary_dcreq_id", table_name="projects")
    with batch_keep_indexes("projects") as batch:
        batch.drop_constraint(op.f("ck_projects_closed"), type_="check")
        batch.drop_constraint(op.f("ck_projects_status"), type_="check")
        batch.drop_constraint("fk_projects_primary_dcreq_id_project_references", type_="foreignkey")
        for col in ("primary_dcreq_id", "closed_by", "closed_at", "created_by", "opened_at", "status"):
            batch.drop_column(col)
    op.drop_index("uq_project_references_dcreq", table_name="project_references")
    with batch_keep_indexes("project_references") as batch:
        batch.drop_constraint(op.f("ck_project_references_dcreq_format"), type_="check")
