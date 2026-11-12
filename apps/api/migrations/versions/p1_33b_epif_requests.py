"""Job intake, ePIF slice (JOB_INTAKE.md §4, §6; DEVICE_DATA_MODEL §5.6): epif_requests + epif_psus.

- epif_requests: one committed ePIF line (install/remove), linked to the job (project_id), its batch
  (job_import_id) and, once created, the device. external_id (the ePIF ID) is unique when set.
- epif_psus: request-time PSU1/PSU2 (raw value, parsed feed + port, part #, position, source).
- import_rows.epif_request_id and job_open_items.epif_request_id (FK SET NULL). The one-target CHECK now counts
  epif_request_id, and uq_job_open_items_unresolved adds it (plus the staging row for target-less items, so two
  skipped rows never collide).
Named p1_33b (the spec's p1_32 planned these tables; p1_34 is reserved for the cable-matrix tables).
Downgrade drops the new tables and columns (row counts printed) and restores the p1_33 CHECK and index.

Revision ID: p1_33b_epif_requests
Revises: p1_33_job_open_items
"""
import sqlalchemy as sa
from alembic import op

from migrations.p0_common import batch_keep_indexes, timestamp_cols

revision = "p1_33b_epif_requests"
down_revision = "p1_33_job_open_items"
branch_labels = None
depends_on = None

_DIGITS = "('0','1','2','3','4','5','6','7','8','9')"
UNRESOLVED = sa.text("status IN ('open','deferred')")
# the target id if there is one, else the staging row: target-less items (skipped rows) dedupe per row
NO_TARGET_ROW = "coalesce(epif_request_id, device_id, connection_id, cable_id, import_row_id, 0)"


def dcreq_sql(col: str) -> str:  # frozen copy of app.modules.jobs.dcreq.dcreq_sql
    digits = " AND ".join(f"substr({col}, {i}, 1) IN {_DIGITS}" for i in range(9, 13))
    return f"length({col}) = 12 AND substr({col}, 1, 8) = 'DCREQ000' AND {digits}"


def _one_target(cols):
    return " + ".join(f"CASE WHEN {c} IS NOT NULL THEN 1 ELSE 0 END" for c in cols) + " <= 1"


def upgrade() -> None:
    T = "epif_requests"
    fks = (("project_id", "projects", "SET NULL"), ("job_import_id", "job_imports", "SET NULL"),
           ("device_type_id", "device_types", "RESTRICT"), ("profile_id", "device_type_profiles", "SET NULL"),
           ("managed_by_group_id", "groups", "SET NULL"), ("rack_id", "racks", "RESTRICT"),
           ("dcreq_reference_id", "project_references", "SET NULL"), ("device_id", "devices", "SET NULL"))
    op.create_table(
        T,
        *timestamp_cols(),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer()),
        sa.Column("job_import_id", sa.Integer()),
        sa.Column("external_id", sa.String(64)),
        sa.Column("action", sa.String(8)),
        sa.Column("status", sa.String(12), nullable=False, server_default="open"),
        sa.Column("requested_host_name", sa.String(255)),
        sa.Column("manufacturer_text", sa.String(255)),
        sa.Column("model_text", sa.String(255)),
        sa.Column("template_text", sa.String(255)),
        sa.Column("device_type_id", sa.Integer()),
        sa.Column("profile_id", sa.Integer()),
        sa.Column("managed_by_group_id", sa.Integer()),
        sa.Column("managed_by_text", sa.String(255)),
        sa.Column("app_service", sa.String(128)),
        sa.Column("rack_id", sa.Integer()),
        sa.Column("row_text", sa.String(64)),
        sa.Column("rack_text", sa.String(64)),
        sa.Column("position_u", sa.Integer()),
        sa.Column("airflow_text", sa.String(64)),
        sa.Column("power_type", sa.String(8)),
        sa.Column("serial_number", sa.String(255)),
        sa.Column("dcreq", sa.String(12)),
        sa.Column("dcreq_reference_id", sa.Integer()),
        sa.Column("device_id", sa.Integer()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{T}")),
        *[sa.ForeignKeyConstraint([c], [f"{t}.id"], ondelete=d, name=op.f(f"fk_{T}_{c}_{t}")) for c, t, d in fks],
        sa.CheckConstraint("action IS NULL OR action IN ('install','remove')", name=op.f(f"ck_{T}_action")),
        sa.CheckConstraint("status IN ('open','approved','done','cancelled')", name=op.f(f"ck_{T}_status")),
        sa.CheckConstraint("position_u IS NULL OR position_u >= 1", name=op.f(f"ck_{T}_position_u")),
        sa.CheckConstraint("power_type IS NULL OR power_type IN ('AC','DC','AC_DC')", name=op.f(f"ck_{T}_power_type")),
        sa.CheckConstraint(f"dcreq IS NULL OR ({dcreq_sql('dcreq')})", name=op.f(f"ck_{T}_dcreq_format")),
    )
    for c, _, _ in fks:
        op.create_index(f"ix_{T}_{c}", T, [c])
    op.create_index("ix_epif_requests_dcreq", T, ["dcreq"])
    op.create_index("ix_epif_requests_status_created_at", T, ["status", "created_at"])
    op.create_index("uq_epif_requests_external_id", T, ["external_id"], unique=True,
                    sqlite_where=sa.text("external_id IS NOT NULL"), postgresql_where=sa.text("external_id IS NOT NULL"))

    P = "epif_psus"
    op.create_table(
        P,
        *timestamp_cols(),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("epif_request_id", sa.Integer(), nullable=False),
        sa.Column("psu_index", sa.Integer(), nullable=False),
        sa.Column("raw_value", sa.String(64)),
        sa.Column("pdu_feed", sa.String(4)),
        sa.Column("pdu_port", sa.Integer()),
        sa.Column("part_number", sa.String(128)),
        sa.Column("position", sa.String(32)),
        sa.Column("source", sa.String(16), nullable=False, server_default="csv"),
        sa.Column("resolved_pdu_device_id", sa.Integer()),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{P}")),
        sa.ForeignKeyConstraint(["epif_request_id"], ["epif_requests.id"], ondelete="CASCADE",
                                name=op.f(f"fk_{P}_epif_request_id_epif_requests")),
        sa.ForeignKeyConstraint(["resolved_pdu_device_id"], ["devices.id"], ondelete="SET NULL",
                                name=op.f(f"fk_{P}_resolved_pdu_device_id_devices")),
        sa.CheckConstraint("psu_index >= 1", name=op.f(f"ck_{P}_psu_index")),
        sa.CheckConstraint("pdu_port IS NULL OR pdu_port >= 0", name=op.f(f"ck_{P}_pdu_port")),
        sa.CheckConstraint("source IN ('csv','import_review','manual')", name=op.f(f"ck_{P}_source")),
    )
    op.create_index("uq_epif_psus_epif_request_id_psu_index", P, ["epif_request_id", "psu_index"], unique=True)
    op.create_index("ix_epif_psus_resolved_pdu_device_id", P, ["resolved_pdu_device_id"])

    with batch_keep_indexes("import_rows") as batch:
        batch.add_column(sa.Column("epif_request_id", sa.Integer()))
        batch.create_foreign_key("fk_import_rows_epif_request_id_epif_requests", "epif_requests",
                                 ["epif_request_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_import_rows_epif_request_id", "import_rows", ["epif_request_id"])

    op.drop_index("uq_job_open_items_unresolved", table_name="job_open_items")
    with batch_keep_indexes("job_open_items") as batch:
        batch.add_column(sa.Column("epif_request_id", sa.Integer()))
        batch.create_foreign_key("fk_job_open_items_epif_request_id_epif_requests", "epif_requests",
                                 ["epif_request_id"], ["id"], ondelete="SET NULL")
        batch.drop_constraint(op.f("ck_job_open_items_one_target"), type_="check")
        batch.create_check_constraint(op.f("ck_job_open_items_one_target"),
                                      _one_target(("epif_request_id", "device_id", "connection_id", "cable_id")))
    op.create_index("ix_job_open_items_epif_request_id", "job_open_items", ["epif_request_id"])
    op.create_index("uq_job_open_items_unresolved", "job_open_items",
                    ["project_id", "item_type", sa.text("coalesce(epif_request_id, 0)"), sa.text("coalesce(device_id, 0)"),
                     sa.text("coalesce(connection_id, 0)"), sa.text("coalesce(cable_id, 0)"), sa.text(NO_TARGET_ROW),
                     sa.text("coalesce(target_field, '')")],
                    unique=True, sqlite_where=UNRESOLVED, postgresql_where=UNRESOLVED)


def downgrade() -> None:
    bind = op.get_bind()
    for t in ("epif_psus", "epif_requests"):
        print(f"p1_33b downgrade: dropping {t} ({bind.execute(sa.text(f'SELECT count(*) FROM {t}')).scalar()} rows)")
    n = bind.execute(sa.text("SELECT count(*) FROM job_open_items WHERE epif_request_id IS NOT NULL")).scalar()
    print(f"p1_33b downgrade: {n} open items lose their epif_request target")
    op.drop_index("uq_job_open_items_unresolved", table_name="job_open_items")
    op.drop_index("ix_job_open_items_epif_request_id", table_name="job_open_items")
    with batch_keep_indexes("job_open_items") as batch:
        batch.drop_constraint(op.f("ck_job_open_items_one_target"), type_="check")
        batch.drop_constraint("fk_job_open_items_epif_request_id_epif_requests", type_="foreignkey")
        batch.drop_column("epif_request_id")
        batch.create_check_constraint(op.f("ck_job_open_items_one_target"),
                                      _one_target(("device_id", "connection_id", "cable_id")))
    op.create_index("uq_job_open_items_unresolved", "job_open_items",
                    ["project_id", "item_type", sa.text("coalesce(device_id, 0)"), sa.text("coalesce(connection_id, 0)"),
                     sa.text("coalesce(cable_id, 0)"), sa.text("coalesce(target_field, '')")],
                    unique=True, sqlite_where=UNRESOLVED, postgresql_where=UNRESOLVED)
    op.drop_index("ix_import_rows_epif_request_id", table_name="import_rows")
    with batch_keep_indexes("import_rows") as batch:
        batch.drop_constraint("fk_import_rows_epif_request_id_epif_requests", type_="foreignkey")
        batch.drop_column("epif_request_id")
    op.drop_table("epif_psus")
    op.drop_table("epif_requests")
