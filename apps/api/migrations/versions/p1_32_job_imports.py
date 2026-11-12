"""Job intake (JOB_INTAKE.md §4, §9.3; renamed from p1_32_epif_import_dcreq): job_imports (one row per
uploaded file on a job) and import_rows (staged CSV rows). The CSV never creates the job, so project_id,
dcreq and dcreq_reference_id are NOT NULL. epif_requests/epif_psus (and import_rows.epif_request_id) are not
built here; they land with the ePIF import slice. Downgrade drops both tables (row counts printed).

Revision ID: p1_32_job_imports
Revises: p1_31_device_project_indexes
"""
import sqlalchemy as sa
from alembic import op

from migrations.p0_common import timestamp_cols

revision = "p1_32_job_imports"
down_revision = "p1_31_device_project_indexes"
branch_labels = None
depends_on = None

_DIGITS = "('0','1','2','3','4','5','6','7','8','9')"


def dcreq_sql(col: str) -> str:  # frozen copy of app.modules.jobs.dcreq.dcreq_sql
    digits = " AND ".join(f"substr({col}, {i}, 1) IN {_DIGITS}" for i in range(9, 13))
    return f"length({col}) = 12 AND substr({col}, 1, 8) = 'DCREQ000' AND {digits}"


def upgrade() -> None:
    ts = sa.DateTime(timezone=True)
    op.create_table(
        "job_imports",
        *timestamp_cols(),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("dcreq", sa.String(12), nullable=False),
        sa.Column("dcreq_reference_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("filename", sa.String(255)),
        sa.Column("sha256", sa.String(64)),
        sa.Column("uploaded_by", sa.String(128)),
        sa.Column("uploaded_at", ts),
        sa.Column("status", sa.String(12), nullable=False, server_default="review"),
        sa.Column("change_set_id", sa.Integer()),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_imports")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT",
                                name=op.f("fk_job_imports_project_id_projects")),
        sa.ForeignKeyConstraint(["dcreq_reference_id"], ["project_references.id"], ondelete="RESTRICT",
                                name=op.f("fk_job_imports_dcreq_reference_id_project_references")),
        sa.ForeignKeyConstraint(["change_set_id"], ["change_sets.id"], ondelete="SET NULL",
                                name=op.f("fk_job_imports_change_set_id_change_sets")),
        sa.CheckConstraint("kind IN ('epif','cable_matrix')", name=op.f("ck_job_imports_kind")),
        sa.CheckConstraint("status IN ('review','committed','abandoned')", name=op.f("ck_job_imports_status")),
        sa.CheckConstraint(dcreq_sql("dcreq"), name=op.f("ck_job_imports_dcreq_format")),
        sa.CheckConstraint("sha256 IS NULL OR length(sha256) = 64", name=op.f("ck_job_imports_sha256")),
    )
    for col in ("project_id", "dcreq", "dcreq_reference_id", "sha256", "change_set_id"):
        op.create_index(f"ix_job_imports_{col}", "job_imports", [col])

    op.create_table(
        "import_rows",
        *timestamp_cols(),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_import_id", sa.Integer(), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("raw_json", sa.Text(), nullable=False),
        sa.Column("result", sa.String(16), nullable=False),
        sa.Column("messages_json", sa.Text()),
        sa.Column("device_id", sa.Integer()),
        sa.Column("connection_id", sa.Integer()),
        sa.Column("cable_id", sa.Integer()),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_import_rows")),
        sa.ForeignKeyConstraint(["job_import_id"], ["job_imports.id"], ondelete="CASCADE",
                                name=op.f("fk_import_rows_job_import_id_job_imports")),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="SET NULL",
                                name=op.f("fk_import_rows_device_id_devices")),
        sa.ForeignKeyConstraint(["connection_id"], ["connections.id"], ondelete="SET NULL",
                                name=op.f("fk_import_rows_connection_id_connections")),
        sa.ForeignKeyConstraint(["cable_id"], ["cables.id"], ondelete="SET NULL",
                                name=op.f("fk_import_rows_cable_id_cables")),
        sa.CheckConstraint("result IN ('ready','warning','held','conflict','committed','skipped')",
                           name=op.f("ck_import_rows_result")),
        sa.CheckConstraint("row_number >= 1", name=op.f("ck_import_rows_row_number")),
    )
    op.create_index("uq_import_rows_job_import_id_row_number", "import_rows", ["job_import_id", "row_number"],
                    unique=True)
    for col in ("device_id", "connection_id", "cable_id"):
        op.create_index(f"ix_import_rows_{col}", "import_rows", [col])


def downgrade() -> None:
    bind = op.get_bind()
    for t in ("import_rows", "job_imports"):
        n = bind.execute(sa.text(f"SELECT count(*) FROM {t}")).scalar()
        print(f"p1_32 downgrade: dropping {t} ({n} rows)")
    op.drop_table("import_rows")
    op.drop_table("job_imports")
