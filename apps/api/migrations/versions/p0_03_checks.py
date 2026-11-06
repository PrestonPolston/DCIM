"""P0-03: named CHECK constraints (with pre-check for violating rows)

Revision ID: p0_03_checks
Revises: p0_02_fk_defaults
"""
from alembic import op

from migrations.p0_common import NC, precheck

revision = "p0_03_checks"
down_revision = "p0_02_fk_defaults"
branch_labels = None
depends_on = None

ORIENTATION = "orientation IS NULL OR orientation IN ('N','E','S','W')"
POS = "(pos_x IS NULL OR pos_x >= 0) AND (pos_y IS NULL OR pos_y >= 0)"
PLACEMENT = (
    "(rack_id IS NULL AND position_u IS NULL) OR "
    "(rack_id IS NOT NULL AND position_u IS NOT NULL AND device_type_id IS NOT NULL)"
)
CHECKS = {  # table -> {short name: expression}
    "devices": {
        "status": "status IN ('install','active','decom')",
        "face": "face IN ('front','rear')",
        "position_u": "position_u IS NULL OR position_u >= 1",
        "placement": PLACEMENT,
        "serial_nonempty": "serial_number IS NULL OR length(trim(serial_number)) > 0",
        "host_name_nonempty": "length(trim(host_name)) > 0",
    },
    "racks": {"u_height": "u_height BETWEEN 1 AND 100", "orientation": ORIENTATION, "pos": POS},
    "rows": {"orientation": ORIENTATION, "pos": POS},
    "device_types": {"u_height": "u_height BETWEEN 0 AND 100"},
}


def upgrade() -> None:
    # trivially safe normalization first
    op.execute("UPDATE devices SET serial_number = NULL WHERE trim(serial_number) = ''")
    op.execute("UPDATE devices SET serial_number = trim(serial_number) WHERE serial_number IS NOT NULL")
    op.execute("UPDATE devices SET host_name = trim(host_name)")
    precheck([
        (f"{table} violating ck_{table}_{name}", f"SELECT id FROM {table} WHERE NOT ({expr})")
        for table, checks in CHECKS.items()
        for name, expr in checks.items()
    ])
    for table, checks in CHECKS.items():
        with op.batch_alter_table(table, recreate="auto", naming_convention=NC) as b:
            for name, expr in checks.items():
                b.create_check_constraint(name, expr)


def downgrade() -> None:
    for table, checks in CHECKS.items():
        with op.batch_alter_table(table, recreate="auto", naming_convention=NC) as b:
            for name in checks:
                b.drop_constraint(op.f(f"ck_{table}_{name}"), type_="check")
