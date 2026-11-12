"""Job intake (JOB_INTAKE.md §3, §9.4): job_open_items, the fill-later queue.

Typed nullable FKs (at most one target, ck_job_open_items_one_target): device_id, connection_id, cable_id, plus
import_row_id (the staging row). epif_request_id and device_psu_assignment_id are added with their tables
(ePIF / PDU slices) and the one-target CHECK is swapped then. Statuses open|deferred|resolved|dismissed; open
and deferred are unresolved. uq_job_open_items_unresolved dedupes unresolved items per job + type + target +
field. Downgrade drops the table (row count printed).

Revision ID: p1_33_job_open_items
Revises: p1_32_job_imports
"""
import sqlalchemy as sa
from alembic import op

from migrations.p0_common import timestamp_cols

revision = "p1_33_job_open_items"
down_revision = "p1_32_job_imports"
branch_labels = None
depends_on = None

T = "job_open_items"
ITEM_TYPES = (
    "epif_not_uploaded", "cable_matrix_not_uploaded",
    "missing_hostname", "missing_profile", "profile_not_usable", "unresolved_cabinet", "missing_position",
    "missing_serial", "missing_psu", "psu_unparsed", "pdu_missing",
    "missing_port", "unresolved_hop", "missing_cable_label", "missing_trail", "media_missing", "ip_missing",
    "space_power_flag", "other",
)
UNRESOLVED = sa.text("status IN ('open','deferred')")
TARGETS = ("device_id", "connection_id", "cable_id")


def _in(col, values):
    return f"{col} IN (" + ",".join(f"'{v}'" for v in values) + ")"


CHECKS = {
    "item_type": _in("item_type", ITEM_TYPES),
    "status": "status IN ('open','deferred','resolved','dismissed')",
    "source": "source IN ('epif','cable_matrix','manual')",
    "deferred": "(status = 'deferred') = (deferred_at IS NOT NULL)",
    "resolved": "(status IN ('open','deferred')) = (resolved_at IS NULL)",
    "dismiss_note": "status <> 'dismissed' OR (note IS NOT NULL AND length(trim(note)) > 0)",
    "one_target": " + ".join(f"CASE WHEN {c} IS NOT NULL THEN 1 ELSE 0 END" for c in TARGETS) + " <= 1",
}
FKS = (("project_id", "projects", "RESTRICT"), ("device_id", "devices", "SET NULL"),
       ("connection_id", "connections", "SET NULL"), ("cable_id", "cables", "SET NULL"),
       ("import_row_id", "import_rows", "SET NULL"), ("change_set_id", "change_sets", "SET NULL"))


def upgrade() -> None:
    ts = sa.DateTime(timezone=True)
    op.create_table(
        T,
        *timestamp_cols(),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("item_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("device_id", sa.Integer()),
        sa.Column("connection_id", sa.Integer()),
        sa.Column("cable_id", sa.Integer()),
        sa.Column("import_row_id", sa.Integer()),
        sa.Column("target_field", sa.String(64)),
        sa.Column("note", sa.Text()),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("created_by", sa.String(128)),
        sa.Column("deferred_at", ts),
        sa.Column("deferred_by", sa.String(128)),
        sa.Column("resolved_at", ts),
        sa.Column("resolved_by", sa.String(128)),
        sa.Column("change_set_id", sa.Integer()),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{T}")),
        *[sa.ForeignKeyConstraint([c], [f"{t}.id"], ondelete=d, name=op.f(f"fk_{T}_{c}_{t}")) for c, t, d in FKS],
        *[sa.CheckConstraint(sql, name=op.f(f"ck_{T}_{short}")) for short, sql in CHECKS.items()],
    )
    for c, _, _ in FKS:
        op.create_index(f"ix_{T}_{c}", T, [c])
    op.create_index("uq_job_open_items_unresolved", T,
                    ["project_id", "item_type", sa.text("coalesce(device_id, 0)"), sa.text("coalesce(connection_id, 0)"),
                     sa.text("coalesce(cable_id, 0)"), sa.text("coalesce(target_field, '')")],
                    unique=True, sqlite_where=UNRESOLVED, postgresql_where=UNRESOLVED)
    op.create_index("ix_job_open_items_queue", T, ["project_id", "status", "item_type", "created_at"],
                    sqlite_where=UNRESOLVED, postgresql_where=UNRESOLVED)


def downgrade() -> None:
    n = op.get_bind().execute(sa.text(f"SELECT count(*) FROM {T}")).scalar()
    print(f"p1_33 downgrade: dropping {T} ({n} rows)")
    op.drop_table(T)
