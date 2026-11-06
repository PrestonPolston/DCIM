"""P0-08: users, sessions, append-only audit_events

Revision ID: p0_08_auth_audit
Revises: p0_07_hostname_unique
"""
import sqlalchemy as sa
from alembic import op

from app.modules.audit.guards import create_append_only_guards, drop_append_only_guards
from migrations.p0_common import timestamp_cols

revision = "p0_08_auth_audit"
down_revision = "p0_07_hostname_unique"
branch_labels = None
depends_on = None

TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("password_hash", sa.String(), nullable=True),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("auth_source", sa.String(), nullable=False, server_default="local"),
        sa.Column("external_subject", sa.String(), nullable=True),
        sa.Column("external_issuer", sa.String(), nullable=True),
        sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("mfa_secret_enc", sa.String(), nullable=True),
        sa.Column("mfa_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("failed_logins", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", TZ, nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("last_login_at", TZ, nullable=True),
        sa.Column("password_changed_at", TZ, nullable=True),
        *timestamp_cols(),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.UniqueConstraint("external_issuer", "external_subject", name="uq_users_external_issuer_external_subject"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL", name="fk_users_created_by_users"),
        sa.CheckConstraint("role IN ('admin','technician','read-only')", name="ck_users_role"),
        sa.CheckConstraint("auth_source IN ('local','oidc')", name="ck_users_auth_source"),
        sa.CheckConstraint("email = lower(email)", name="ck_users_email_lower"),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("auth_provider", sa.String(), nullable=False),
        sa.Column("mfa_satisfied", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("csrf_token", sa.String(), nullable=False),
        sa.Column("created_at", TZ, nullable=False),
        sa.Column("expires_at", TZ, nullable=False),
        sa.Column("last_seen_at", TZ, nullable=False),
        sa.Column("ip", sa.String(), nullable=True),
        sa.Column("user_agent", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_sessions"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name="fk_sessions_user_id_users"),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("occurred_at", TZ, nullable=False, server_default=sa.func.now()),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("actor_ip", sa.String(), nullable=True),
        sa.Column("request_id", sa.String(), nullable=True),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("before_json", sa.Text(), nullable=True),
        sa.Column("after_json", sa.Text(), nullable=True),
        sa.Column("import_batch_id", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_audit_events"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL",
                                name="fk_audit_events_actor_user_id_users"),
    )
    op.create_index("ix_audit_events_entity", "audit_events", ["entity_type", "entity_id", "occurred_at"])
    op.create_index("ix_audit_events_actor", "audit_events", ["actor_user_id", "occurred_at"])
    op.create_index("ix_audit_events_occurred_at", "audit_events", ["occurred_at"])
    create_append_only_guards(op.get_bind())


def downgrade() -> None:
    drop_append_only_guards(op.get_bind())
    op.drop_table("audit_events")
    op.drop_table("sessions")
    op.drop_table("users")

