"""Items 47d-f/48a (D44-D47): audit_events.via + retention_class, change_sets export record, restored_devices.

SQLite: batch-altering audit_events recreates the table, which drops the append-only triggers, so they are
re-created afterwards (upgrade and downgrade). PG: plain ALTERs, the trigger stays; it is lifted only for the
one UPDATE that marks existing hard_delete snapshots 'restorable' (recorded as an audit.migration event).

Revision ID: p1_19_removal_hardening
Revises: p1_17b_profile_versions
"""
import sqlalchemy as sa
from alembic import op

from app.modules.audit.guards import create_append_only_guards, drop_append_only_guards
from migrations.p0_common import batch_keep_indexes

revision = "p1_19_removal_hardening"
down_revision = "p1_17b_profile_versions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    drop_append_only_guards(bind)
    with batch_keep_indexes("audit_events") as batch:
        batch.add_column(sa.Column("via", sa.String(16)))
        batch.add_column(sa.Column("retention_class", sa.String(16), nullable=False, server_default="standard"))
        batch.create_check_constraint("via", "via IS NULL OR via IN ('api','script','migration','csv_import')")
        batch.create_check_constraint("retention_class", "retention_class IN ('standard','restorable')")
    op.create_index("ix_audit_events_retention", "audit_events", ["retention_class", "occurred_at"])
    marked = bind.execute(sa.text(
        "UPDATE audit_events SET retention_class = 'restorable' WHERE action IN ('hard_delete', 'device.hard_delete')")).rowcount
    bind.execute(sa.text(
        "INSERT INTO audit_events(occurred_at, action, entity_type, after_json, via, retention_class) "
        "VALUES (CURRENT_TIMESTAMP, 'audit.migration', 'audit_events', :a, 'migration', 'standard')"),
        {"a": f'{{"migration": "p1_19_removal_hardening", "marked_restorable": {marked}}}'})
    create_append_only_guards(bind)

    with batch_keep_indexes("change_sets") as batch:
        batch.add_column(sa.Column("export_path", sa.Text()))
        batch.add_column(sa.Column("export_sha256", sa.String(64)))
        batch.create_check_constraint("export_sha256", "export_sha256 IS NULL OR length(export_sha256) = 64")

    op.create_table(
        "restored_devices",
        sa.Column("source_change_set_id", sa.Integer(), nullable=False),
        sa.Column("original_device_id", sa.Integer(), nullable=False),
        sa.Column("restored_device_id", sa.Integer()),
        sa.Column("restore_change_set_id", sa.Integer(), nullable=False),
        sa.Column("restored_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("source_change_set_id", "original_device_id", name="pk_restored_devices"),
        sa.ForeignKeyConstraint(["source_change_set_id"], ["change_sets.id"], ondelete="RESTRICT",
                                name="fk_restored_devices_source_change_set_id_change_sets"),
        sa.ForeignKeyConstraint(["restore_change_set_id"], ["change_sets.id"], ondelete="RESTRICT",
                                name="fk_restored_devices_restore_change_set_id_change_sets"),
        sa.ForeignKeyConstraint(["restored_device_id"], ["devices.id"], ondelete="SET NULL",
                                name="fk_restored_devices_restored_device_id_devices"),
    )
    op.create_index("ix_restored_devices_restore_change_set_id", "restored_devices", ["restore_change_set_id"])


def downgrade() -> None:
    op.drop_index("ix_restored_devices_restore_change_set_id", table_name="restored_devices")
    op.drop_table("restored_devices")
    with batch_keep_indexes("change_sets") as batch:
        batch.drop_constraint("export_sha256", type_="check")
        batch.drop_column("export_sha256")
        batch.drop_column("export_path")
    bind = op.get_bind()
    drop_append_only_guards(bind)
    op.drop_index("ix_audit_events_retention", table_name="audit_events")
    with batch_keep_indexes("audit_events") as batch:
        batch.drop_constraint("retention_class", type_="check")
        batch.drop_constraint("via", type_="check")
        batch.drop_column("retention_class")
        batch.drop_column("via")
    create_append_only_guards(bind)
