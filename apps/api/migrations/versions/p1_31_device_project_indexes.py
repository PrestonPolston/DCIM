"""Job intake (JOB_INTAKE.md §9.2, unchanged from the held plan): devices(project_id, status) for per-job
device counts by status, and devices(updated_at). Indexes only.

Revision ID: p1_31_device_project_indexes
Revises: p1_30_project_dcreq
"""
from alembic import op

revision = "p1_31_device_project_indexes"
down_revision = "p1_30_project_dcreq"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_devices_project_id_status", "devices", ["project_id", "status"])
    op.create_index("ix_devices_updated_at", "devices", ["updated_at"])


def downgrade() -> None:
    op.drop_index("ix_devices_updated_at", table_name="devices")
    op.drop_index("ix_devices_project_id_status", table_name="devices")
