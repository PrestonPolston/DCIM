from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Text, func
from sqlmodel import Field, SQLModel

from app.timestamps import utcnow


# Append-only security/audit log (AUTH_RBAC_PLAN §5); UPDATE/DELETE blocked by DB triggers
class AuditEventRow(SQLModel, table=True):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_entity", "entity_type", "entity_id", "occurred_at"),
        Index("ix_audit_events_actor", "actor_user_id", "occurred_at"),
        Index("ix_audit_events_retention", "retention_class", "occurred_at"),
        CheckConstraint("via IS NULL OR via IN ('api','script','migration','csv_import')", name="via"),
        CheckConstraint("retention_class IN ('standard','restorable')", name="retention_class"),
    )

    id: int | None = Field(default=None, primary_key=True)
    occurred_at: datetime | None = Field(
        default_factory=utcnow, nullable=False, index=True, sa_type=DateTime(timezone=True),
        sa_column_kwargs={"server_default": func.now()},
    )
    actor_user_id: int | None = Field(default=None, foreign_key="users.id", ondelete="SET NULL")
    actor_ip: str | None = None
    request_id: str | None = None
    action: str
    entity_type: str
    entity_id: int | None = None
    before_json: str | None = Field(default=None, sa_type=Text)
    after_json: str | None = Field(default=None, sa_type=Text)
    import_batch_id: str | None = None
    via: str | None = Field(default=None, max_length=16)  # p1_19 (D44)
    # p1_19 (D45): 'restorable' = deletion snapshot, kept >= 24 months; set at insert (table is append-only)
    retention_class: str = Field(default="standard", max_length=16,
                                 sa_column_kwargs={"server_default": "standard"})
