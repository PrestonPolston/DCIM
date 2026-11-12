"""Cable matrix rest (JOB_INTAKE.md §1, §7, §9 item 5; DEVICE_DATA_MODEL §7): what the cable-matrix import needs.

- cables: external_id (matrix ID, unique when set), trail (ix), cable_mode, status (planned/active/removed,
  default active) + removed_at, project_id (the job, FK SET NULL). uq_cables_label now ignores removed cables.
- connections: status + removed_at, action (add/remove/move), change_set_id (FK SET NULL). The (port, lane)
  uniques become partial on status <> 'removed'.
- connection_hops: ordered panel ports per connection (seq 1..32), one active hop per (port, lane).
- port_ip_config: network / VLAN / native VLAN / IP / prefix / gateway per port.
Existing rows become status 'active' (server default). Downgrade refuses (listing ids) when removed rows would
collide with the restored full uniques, then drops the new tables and columns (row counts printed).

Revision ID: p1_34_cable_matrix_rest
Revises: p1_33b_epif_requests
"""
import sqlalchemy as sa
from alembic import op

from migrations.p0_common import batch_keep_indexes, precheck, timestamp_cols

revision = "p1_34_cable_matrix_rest"
down_revision = "p1_33b_epif_requests"
branch_labels = None
depends_on = None

NOT_REMOVED = "status <> 'removed'"
STATUS = "status IN ('planned','active','removed')"
REMOVED = "(status = 'removed') = (removed_at IS NOT NULL)"


def _where(cond: str) -> dict:
    return {"sqlite_where": sa.text(cond), "postgresql_where": sa.text(cond)}


def upgrade() -> None:
    op.drop_index("uq_cables_label", table_name="cables")
    with batch_keep_indexes("cables") as batch:
        batch.add_column(sa.Column("external_id", sa.String(64)))
        batch.add_column(sa.Column("trail", sa.String(128)))
        batch.add_column(sa.Column("cable_mode", sa.String(8)))
        batch.add_column(sa.Column("status", sa.String(8), nullable=False, server_default="active"))
        batch.add_column(sa.Column("removed_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("project_id", sa.Integer()))
        batch.create_foreign_key("fk_cables_project_id_projects", "projects", ["project_id"], ["id"],
                                 ondelete="SET NULL")
        batch.create_check_constraint(op.f("ck_cables_cable_mode"),
                                      "cable_mode IS NULL OR cable_mode IN ('smf','mmf','copper','dac','aoc','mpo')")
        batch.create_check_constraint(op.f("ck_cables_status"), STATUS)
        batch.create_check_constraint(op.f("ck_cables_removed"), REMOVED)
    op.create_index("uq_cables_label", "cables", [sa.text("lower(label)")], unique=True,
                    **_where(f"label IS NOT NULL AND {NOT_REMOVED}"))
    op.create_index("uq_cables_external_id", "cables", ["external_id"], unique=True,
                    **_where("external_id IS NOT NULL"))
    op.create_index("ix_cables_trail", "cables", ["trail"])
    op.create_index("ix_cables_project_id", "cables", ["project_id"])

    op.drop_index("uq_connections_port1_lane_active", table_name="connections")
    op.drop_index("uq_connections_port2_lane_active", table_name="connections")
    with batch_keep_indexes("connections") as batch:
        batch.add_column(sa.Column("status", sa.String(8), nullable=False, server_default="active"))
        batch.add_column(sa.Column("action", sa.String(8)))
        batch.add_column(sa.Column("removed_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("change_set_id", sa.Integer()))
        batch.create_foreign_key("fk_connections_change_set_id_change_sets", "change_sets", ["change_set_id"],
                                 ["id"], ondelete="SET NULL")
        batch.create_check_constraint(op.f("ck_connections_status"), STATUS)
        batch.create_check_constraint(op.f("ck_connections_action"),
                                      "action IS NULL OR action IN ('add','remove','move')")
        batch.create_check_constraint(op.f("ck_connections_removed"), REMOVED)
    op.create_index("uq_connections_port1_lane_active", "connections", ["port1_id", "port1_lane"], unique=True,
                    **_where(NOT_REMOVED))
    op.create_index("uq_connections_port2_lane_active", "connections", ["port2_id", "port2_lane"], unique=True,
                    **_where(NOT_REMOVED))
    op.create_index("ix_connections_change_set_id", "connections", ["change_set_id"])

    H = "connection_hops"
    op.create_table(
        H,
        *timestamp_cols(),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("connection_id", sa.Integer(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("port_id", sa.Integer(), nullable=False),
        sa.Column("lane", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cable_id", sa.Integer()),
        sa.Column("label", sa.String(128)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{H}")),
        sa.ForeignKeyConstraint(["connection_id"], ["connections.id"], ondelete="CASCADE",
                                name=op.f(f"fk_{H}_connection_id_connections")),
        sa.ForeignKeyConstraint(["port_id"], ["device_ports.id"], ondelete="RESTRICT",
                                name=op.f(f"fk_{H}_port_id_device_ports")),
        sa.ForeignKeyConstraint(["cable_id"], ["cables.id"], ondelete="SET NULL", name=op.f(f"fk_{H}_cable_id_cables")),
        sa.CheckConstraint("seq >= 1 AND seq <= 32", name=op.f(f"ck_{H}_seq")),
        sa.CheckConstraint("lane >= 0", name=op.f(f"ck_{H}_lane")),
    )
    op.create_index("uq_connection_hops_connection_id_seq", H, ["connection_id", "seq"], unique=True)
    op.create_index("uq_connection_hops_port_lane_active", H, ["port_id", "lane"], unique=True, **_where("is_active"))
    op.create_index("ix_connection_hops_port_id", H, ["port_id"])
    op.create_index("ix_connection_hops_cable_id", H, ["cable_id"])

    P = "port_ip_config"
    op.create_table(
        P,
        *timestamp_cols(),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("port_id", sa.Integer(), nullable=False),
        sa.Column("network", sa.String(64)),
        sa.Column("vlan", sa.Integer()),
        sa.Column("native_vlan", sa.Integer()),
        sa.Column("ip_address", sa.String(45)),
        sa.Column("prefix_len", sa.Integer()),
        sa.Column("default_gateway", sa.String(45)),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{P}")),
        sa.ForeignKeyConstraint(["port_id"], ["device_ports.id"], ondelete="CASCADE",
                                name=op.f(f"fk_{P}_port_id_device_ports")),
        sa.CheckConstraint("vlan IS NULL OR (vlan >= 1 AND vlan <= 4094)", name=op.f(f"ck_{P}_vlan")),
        sa.CheckConstraint("native_vlan IS NULL OR (native_vlan >= 1 AND native_vlan <= 4094)",
                           name=op.f(f"ck_{P}_native_vlan")),
        sa.CheckConstraint("prefix_len IS NULL OR (prefix_len >= 0 AND prefix_len <= 128)",
                           name=op.f(f"ck_{P}_prefix_len")),
    )
    op.create_index("ix_port_ip_config_port_id", P, ["port_id"])


def downgrade() -> None:
    precheck([
        ("removed connections whose (port1, lane) is reused",
         "SELECT c.id FROM connections c JOIN connections o ON o.id <> c.id AND o.port1_id = c.port1_id "
         "AND o.port1_lane = c.port1_lane WHERE c.status = 'removed'"),
        ("removed connections whose (port2, lane) is reused",
         "SELECT c.id FROM connections c JOIN connections o ON o.id <> c.id AND o.port2_id = c.port2_id "
         "AND o.port2_lane = c.port2_lane WHERE c.status = 'removed'"),
        ("removed cables whose label is reused",
         "SELECT c.id FROM cables c JOIN cables o ON o.id <> c.id AND lower(o.label) = lower(c.label) "
         "WHERE c.status = 'removed'"),
    ])
    bind = op.get_bind()
    for t in ("connection_hops", "port_ip_config"):
        print(f"p1_34 downgrade: dropping {t} ({bind.execute(sa.text(f'SELECT count(*) FROM {t}')).scalar()} rows)")
    for t, cond in (("cables", "trail IS NOT NULL OR external_id IS NOT NULL OR project_id IS NOT NULL"),
                    ("connections", "status <> 'active' OR action IS NOT NULL")):
        n = bind.execute(sa.text(f"SELECT count(*) FROM {t} WHERE {cond}")).scalar()
        print(f"p1_34 downgrade: {n} {t} lose their p1_34 columns")
    op.drop_table("port_ip_config")
    op.drop_table("connection_hops")

    op.drop_index("ix_connections_change_set_id", table_name="connections")
    op.drop_index("uq_connections_port1_lane_active", table_name="connections")
    op.drop_index("uq_connections_port2_lane_active", table_name="connections")
    with batch_keep_indexes("connections") as batch:
        batch.drop_constraint(op.f("ck_connections_removed"), type_="check")
        batch.drop_constraint(op.f("ck_connections_action"), type_="check")
        batch.drop_constraint(op.f("ck_connections_status"), type_="check")
        batch.drop_constraint("fk_connections_change_set_id_change_sets", type_="foreignkey")
        for c in ("change_set_id", "removed_at", "action", "status"):
            batch.drop_column(c)
    op.create_index("uq_connections_port1_lane_active", "connections", ["port1_id", "port1_lane"], unique=True)
    op.create_index("uq_connections_port2_lane_active", "connections", ["port2_id", "port2_lane"], unique=True)

    for ix in ("ix_cables_project_id", "ix_cables_trail", "uq_cables_external_id", "uq_cables_label"):
        op.drop_index(ix, table_name="cables")
    with batch_keep_indexes("cables") as batch:
        for ck in ("ck_cables_removed", "ck_cables_status", "ck_cables_cable_mode"):
            batch.drop_constraint(op.f(ck), type_="check")
        batch.drop_constraint("fk_cables_project_id_projects", type_="foreignkey")
        for c in ("project_id", "removed_at", "status", "cable_mode", "trail", "external_id"):
            batch.drop_column(c)
    op.create_index("uq_cables_label", "cables", [sa.text("lower(label)")], unique=True,
                    **_where("label IS NOT NULL"))
