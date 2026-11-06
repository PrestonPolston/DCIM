"""DB-level append-only guards for audit_events (used by the migration and tests)."""
# Append-only: block UPDATE/DELETE on audit_events. Purges after archiving must
# temporarily drop the guard (app/scripts/audit_archive.py does this).
def create_append_only_guards(bind) -> None:
    if bind.dialect.name == "sqlite":
        for verb in ("UPDATE", "DELETE"):
            bind.exec_driver_sql(
                f"CREATE TRIGGER audit_events_no_{verb.lower()} BEFORE {verb} ON audit_events "
                f"BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END"
            )
    elif bind.dialect.name == "postgresql":
        bind.exec_driver_sql(
            "CREATE FUNCTION audit_events_append_only() RETURNS trigger LANGUAGE plpgsql AS "
            "$$ BEGIN RAISE EXCEPTION 'audit_events is append-only'; END $$"
        )
        bind.exec_driver_sql(
            "CREATE TRIGGER audit_events_append_only BEFORE UPDATE OR DELETE ON audit_events "
            "FOR EACH ROW EXECUTE FUNCTION audit_events_append_only()"
        )


def drop_append_only_guards(bind) -> None:
    if bind.dialect.name == "sqlite":
        for verb in ("update", "delete"):
            bind.exec_driver_sql(f"DROP TRIGGER IF EXISTS audit_events_no_{verb}")
    elif bind.dialect.name == "postgresql":
        bind.exec_driver_sql("DROP TRIGGER IF EXISTS audit_events_append_only ON audit_events")
        bind.exec_driver_sql("DROP FUNCTION IF EXISTS audit_events_append_only()")
