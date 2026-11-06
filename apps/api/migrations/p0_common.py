"""Shared helpers for the P0 migrations (naming convention, pre-checks)."""
import sqlalchemy as sa
from alembic import op

NC = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def precheck(checks: list[tuple[str, str]]) -> None:
    """Fail (listing ids) if any query returns rows. checks = [(label, SELECT id ...)]."""
    bind = op.get_bind()
    problems = []
    for label, query in checks:
        ids = [r[0] for r in bind.execute(sa.text(query)).fetchall()]
        if ids:
            problems.append(f"{label}: ids {ids[:20]}")
    if problems:
        raise RuntimeError("Fix these rows before migrating:\n  " + "\n  ".join(problems))


def timestamp_cols() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


from contextlib import contextmanager


@contextmanager
def batch_keep_indexes(table: str, **kw):
    """batch_alter_table that survives SQLite table recreation: expression/partial indexes
    (which SQLite reflection drops) are captured from sqlite_master and re-created afterwards."""
    bind = op.get_bind()
    saved = []
    if bind.dialect.name == "sqlite":
        saved = bind.execute(sa.text(
            "SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name=:t AND sql IS NOT NULL"
        ), {"t": table}).fetchall()
    import warnings

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Skipped unsupported reflection")
        with op.batch_alter_table(table, naming_convention=NC, **kw) as batch:
            yield batch
    for name, sql in saved:
        bind.execute(sa.text(f'DROP INDEX IF EXISTS "{name}"'))
        try:
            bind.execute(sa.text(sql))
        except sa.exc.OperationalError as exc:  # index on a column this batch dropped
            if "no such column" not in str(exc):
                raise
