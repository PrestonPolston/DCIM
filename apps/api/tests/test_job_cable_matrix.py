"""Job intake v1, slice 3: cable-matrix CSV onto a job. A row commits when both A and Z ports resolve; hops,
trail, label, media and IP are fill-later items; conflicts skip the row and the batch continues."""
from sqlmodel import Session, select

from app.modules.audit.models import AuditEventRow
from app.modules.connections.models import (
    CableRow, ConnectionHopRow, ConnectionRow, DevicePortRow, PortIpConfigRow,
)
from app.modules.jobs.models import ImportRowRow
from tests.test_locations import dtype, make_rack

CSV = {"Content-Type": "text/csv"}
HEAD = ("ID,Trail,Action,Cable Type,Cable Mode,Cable Label,A Name,A Row,A Rack,A Slot,A Port,A Lane,"
        "Z Name,Z Port,Z Speed,VLAN,IP,Subnet Mask,Hop1,Hop2")


def line(mid="", trail="T-1", action="Add", ctype="LC", mode="SMF", label="", a="sw1", a_row="", a_rack="",
         a_slot="", a_port="Eth1", a_lane="", z="srv1", z_port="eth0", speed="", vlan="", ip="", mask="",
         hop1="", hop2=""):
    return ",".join([mid, trail, action, ctype, mode, label, a, a_row, a_rack, a_slot, a_port, a_lane, z, z_port,
                     speed, vlan, ip, mask, hop1, hop2])


def body(*rows, head=HEAD):
    return head + "\n" + "\n".join(rows) + "\n"


def _job(client, dcreq="DCREQ0001234"):
    r = client.post("/jobs", json={"dcreq": dcreq})
    assert r.status_code == 201, r.text
    return r.json()


def upload(client, job_id, text, filename="cables.csv"):
    return client.post(f"/jobs/{job_id}/imports", params={"kind": "cable_matrix", "filename": filename},
                       content=text, headers=CSV)


def _env(client, engine):
    rack = make_rack(client)
    t = dtype(client, 1, name="1U")
    ids = {}
    for u, host in enumerate(("sw1", "srv1", "srv2", "srv3", "srv4", "pnl1"), start=1):
        r = client.post("/devices", json={"host_name": host, "rack_id": rack["id"], "device_type_id": t["id"],
                                          "position_u": u})
        assert r.status_code == 201, r.text
        ids[host] = r.json()["id"]
    with Session(engine) as s:  # panel: rear MPO R1 (4 positions) -> fronts F1..F4; switch breakout port Eth1/1
        rear = DevicePortRow(device_id=ids["pnl1"], name="R1", role="rear", lanes=4)
        s.add(rear)
        s.flush()
        for i in range(1, 5):
            s.add(DevicePortRow(device_id=ids["pnl1"], name=f"F{i}", role="front", rear_port_id=rear.id,
                                rear_position=i))
        s.add(DevicePortRow(device_id=ids["sw1"], name="Eth1/1", lanes=4))
        s.commit()
    return rack, ids


def items(client, job_id, **params):
    return client.get(f"/jobs/{job_id}/open-items", params={"status": "all", "limit": 500, **params}).json()


# ---- headers ----
def test_headers(client):
    j = _job(client)
    r = upload(client, j["id"], "A Name,A Port,Z Name\nsw1,Eth1,srv1\n")
    assert r.status_code == 422 and r.json()["detail"] == {
        "code": "missing_columns", "message": "The cable matrix needs these columns: Z Port", "columns": ["Z Port"]}
    r = upload(client, j["id"], body(line(), head=HEAD.replace("Hop2", "iLO Password")))
    assert r.json()["detail"]["code"] == "import_forbidden_columns" and r.json()["detail"]["headers"] == ["iLO Password"]
    r = upload(client, j["id"], body(line(), head=HEAD.replace("Hop2", "Hop9")))
    assert r.json()["detail"] == {"code": "unknown_columns", "message": "Unknown columns: Hop9", "columns": ["Hop9"]}
    # aliases: A Side Hostname / Slot/Blade/Card / Z End Interface / Hop 1
    r = upload(client, j["id"], "A Side Hostname,A Slot/Blade/Card,A Port,Z Name,Z End Interface,Hop 1\nx,1,p,y,q,\n")
    assert r.status_code == 201, r.text


def test_csv_never_creates_a_job(client):
    r = upload(client, "DCREQ0009999", body(line()))
    assert r.status_code == 404 and r.json()["detail"]["code"] == "job_not_found"


# ---- preview + commit ----
def test_commit_resolved_rows_held_unresolved_ends_skips_conflicts(client, engine):
    _, ids = _env(client, engine)
    j = _job(client)
    text = body(
        line(mid="C1", label="CAB-1", a_port="Eth1", z="srv1", z_port="eth0", speed="25G"),  # 1 ready (ports created)
        line(mid="C2", trail="", label="", a_port="Eth2", z="srv2", z_port="eth0"),       # 2 warning: no trail/label
        line(mid="C3", label="CAB-3", z="ghost", z_port="eth0", a_port="Eth3"),           # 3 held: unknown Z device
        line(mid="C4", label="CAB-4", a_port="", z="srv3", z_port="eth0"),                # 4 held: blank A port
        line(mid="C5", label="CAB-5", a_port="Eth5", z="srv1", z_port="eth0"),            # 5 conflict: srv1 eth0 (row 1)
        line(mid="C6", label="CAB-6", a_port="Eth6", z="srv4", z_port="eth0", hop1="nope:F9"),  # 6 warning: hop
        line(mid="C1", label="CAB-7", a_port="Eth7", z="srv4", z_port="eth1"),            # 7 conflict: repeated ID
        line(mid="C8", label="cab-1", a_port="Eth8", z="srv4", z_port="eth2"),            # 8 conflict: label (row 1)
        line(mid="C9", label="CAB-9", a_port="Eth9", z="sw1", z_port="Eth9"),             # 9 conflict: A = Z
    )
    r = upload(client, j["id"], text)
    assert r.status_code == 201, r.text
    imp = r.json()
    assert imp["kind"] == "cable_matrix" and imp["status"] == "review"
    res = [x["result"] for x in imp["rows"]]
    assert res == ["ready", "warning", "held", "held", "conflict", "warning", "conflict", "conflict", "conflict"]
    r1 = imp["rows"][0]
    assert r1["matrix_id"] == "C1" and r1["a"] == "sw1:Eth1" and r1["z"] == "srv1:eth0" and r1["trail"] == "T-1"
    assert {m["code"] for m in r1["messages"]} == {"port_created"}
    codes = lambda i: {m["code"] for m in imp["rows"][i]["messages"]}  # noqa: E731
    assert {"missing_trail", "missing_cable_label"} <= codes(1)
    assert "unresolved_device" in codes(2) and "missing_port" in codes(3)
    assert "port_in_use" in codes(4) and "duplicate_matrix_id" in codes(6)
    assert "cable_label_conflict" in codes(7) and "self_connection" in codes(8)
    assert "hop_unresolved" in codes(5)
    with Session(engine) as s:  # staging wrote nothing live
        assert s.exec(select(ConnectionRow)).all() == [] and s.exec(select(CableRow)).all() == []
        assert s.exec(select(DevicePortRow).where(DevicePortRow.name == "Eth1")).all() == []

    c = client.post(f"/jobs/{j['id']}/imports/{imp['id']}/commit")
    assert c.status_code == 200, c.text
    c = c.json()
    assert [x["row_number"] for x in c["committed"]] == [1, 2, 6]
    assert [x["row_number"] for x in c["held"]] == [3, 4]
    assert [x["row_number"] for x in c["skipped"]] == [5, 7, 8, 9]
    assert c["skipped"][0]["reasons"][0]["code"] == "port_in_use"
    assert c["committed"][0]["a"] == "sw1:Eth1" and c["committed"][0]["cable_label"] == "CAB-1"
    assert c["job"]["connection_count"] == 3 and c["imports"][0]["counts"]["committed"] == 3
    by = {}
    for i in items(client, j["id"]):
        by.setdefault(i["item_type"], []).append(i)
    assert by["cable_matrix_not_uploaded"][0]["status"] == "resolved"
    assert by["epif_not_uploaded"][0]["status"] == "open"
    conn_rows = {x["row_number"]: x for x in c["committed"]}
    trail = by["missing_trail"][0]
    assert trail["cable_id"] == conn_rows[2]["cable_id"] and trail["source"] == "cable_matrix"
    assert by["missing_cable_label"][0]["cable_id"] == conn_rows[2]["cable_id"]
    hop = by["unresolved_hop"][0]
    assert hop["connection_id"] == conn_rows[6]["connection_id"] and hop["target_field"] == "hop_1"
    assert hop["cable_label"] == "CAB-6" and hop["cable_trail"] == "T-1"  # joined through the connection's cable
    held = {i["target_field"] for i in by["missing_hostname"] + by["missing_port"]}
    assert held == {"host_name_z", "port_a"}
    assert all(i["import_row_id"] and i["connection_id"] is None for i in by["missing_port"])
    with Session(engine) as s:
        conns = s.exec(select(ConnectionRow).order_by(ConnectionRow.id)).all()
        assert [(x.status, x.action, x.port1_lane, x.port2_lane) for x in conns] == [("active", "add", 0, 0)] * 3
        cab = s.get(CableRow, conns[0].cable_id)
        assert (cab.label, cab.trail, cab.external_id, cab.cable_type, cab.cable_mode, cab.project_id) == (
            "CAB-1", "T-1", "C1", "LC", "smf", j["id"])
        eth0 = s.exec(select(DevicePortRow).where(DevicePortRow.device_id == ids["srv1"])).one()
        assert (eth0.name, eth0.role, eth0.speed_mbps) == ("eth0", "endpoint", 25000)
        assert s.exec(select(ImportRowRow).where(ImportRowRow.connection_id.is_not(None))).all()
        assert len(s.exec(select(AuditEventRow).where(AuditEventRow.action == "connection.create")).all()) == 3
    # the existing connection API sees them
    lst = client.get("/connections", params={"device_id": ids["sw1"]}).json()
    assert {x["cable"]["label"] for x in lst} >= {"CAB-1"}


def test_breakout_through_mpo_panel(client, engine):
    _, ids = _env(client, engine)
    j = _job(client)
    text = body(
        line(mid="B1", label="BO-1", a_port="Eth1/1", z="srv1", hop1="pnl1:F1", hop2="pnl1:R1"),
        line(mid="B2", label="BO-2", a_port="Eth1/1", z="srv2", hop1="pnl1:F2", hop2="pnl1:R1"),
        line(mid="B3", label="BO-3", a_port="Eth1/1", z="srv3", hop1="pnl1:F2", hop2="pnl1:R1"),  # F2 again
        line(mid="B4", label="BO-4", a_port="Eth1/1", a_lane="0", z="srv4"),                     # whole port
        line(mid="B5", label="BO-5", a_port="Eth1/1", a_lane="7", z="srv4", z_port="eth9"),     # > 4 lanes
    )
    imp = upload(client, j["id"], text).json()
    assert [x["result"] for x in imp["rows"]] == ["ready", "ready", "conflict", "conflict", "conflict"]
    assert imp["rows"][2]["messages"][-1]["code"] in ("hop_in_use", "port_in_use")
    assert {m["code"] for m in imp["rows"][3]["messages"]} == {"port_created", "port_in_use"}
    assert {m["code"] for m in imp["rows"][4]["messages"]} == {"port_created", "lane_out_of_range"}
    c = client.post(f"/jobs/{j['id']}/commit").json()
    assert len(c["committed"]) == 2
    with Session(engine) as s:
        sw = s.exec(select(DevicePortRow).where(DevicePortRow.name == "Eth1/1")).one()
        conns = s.exec(select(ConnectionRow).order_by(ConnectionRow.id)).all()
        lanes = sorted(x.port1_lane if x.port1_id == sw.id else x.port2_lane for x in conns)
        assert lanes == [1, 2]
        hops = s.exec(select(ConnectionHopRow).order_by(ConnectionHopRow.id)).all()
        assert [(h.seq, h.lane, h.is_active) for h in hops] == [(1, 0, True), (2, 1, True), (1, 0, True), (2, 2, True)]
    # a later file can't reuse lane 1 of the switch port or the F1 hop
    again = upload(client, j["id"], body(line(mid="B6", label="BO-6", a_port="Eth1/1", a_lane="1", z="srv3",
                                              hop1="pnl1:F1")), filename="b.csv").json()
    assert {m["code"] for m in again["rows"][0]["messages"]} >= {"port_in_use", "hop_in_use"}


def test_db_conflicts_and_matrix_id_reimport(client, engine):
    _, ids = _env(client, engine)
    r = client.post("/connections", json={"a_device_id": ids["srv1"], "a_port_name": "eth0", "b_device_id": ids["srv2"],
                                          "b_port_name": "eth0", "cable_label": "TAKEN"})
    assert r.status_code == 201, r.text
    j = _job(client)
    text = body(line(mid="D1", label="X1", z="srv1", z_port="eth0"),                  # port connected (DB)
                line(mid="D2", label="taken", a_port="Eth2", z="srv3"),                 # label (DB, any case)
                line(mid="D3", label="X3", a_port="Eth3", z="srv4"))
    imp = upload(client, j["id"], text).json()
    assert [x["result"] for x in imp["rows"]] == ["conflict", "conflict", "ready"]
    client.post(f"/jobs/{j['id']}/imports/{imp['id']}/commit")
    nxt = upload(client, j["id"], body(line(mid="D3", label="X4", a_port="Eth4", z="srv4", z_port="eth1")),
                 filename="n.csv").json()
    assert nxt["rows"][0]["messages"][0]["code"] == "matrix_id_already_imported"


def test_commit_revalidates(client, engine):
    _, ids = _env(client, engine)
    j = _job(client)
    imp = upload(client, j["id"], body(line(mid="R1", label="L1", z="srv1", z_port="eth0"))).json()
    assert imp["rows"][0]["result"] == "ready"
    client.post("/connections", json={"a_device_id": ids["srv1"], "a_port_name": "eth0", "b_device_id": ids["srv2"],
                                      "b_port_name": "eth0"})
    c = client.post(f"/jobs/{j['id']}/imports/{imp['id']}/commit").json()
    assert c["committed"] == [] and c["skipped"][0]["reasons"][0]["code"] == "port_in_use"


def test_ip_config_and_bad_values(client, engine):
    _env(client, engine)
    j = _job(client)
    text = body(line(mid="I1", label="IP1", z="srv1", vlan="100", ip="10.0.0.5", mask="255.255.255.0"),
                line(mid="I2", label="IP2", a_port="Eth2", z="srv2", vlan="5000", ip="10.0.0.999", mask="/24",
                     speed="fast", ctype="Cat6", mode=""))
    imp = upload(client, j["id"], text).json()
    assert [x["result"] for x in imp["rows"]] == ["ready", "warning"]
    codes = [m["code"] for m in imp["rows"][1]["messages"]]
    assert codes.count("ip_invalid") == 2 and "speed_unparsed" in codes and "cable_type_unknown" in codes
    assert "media_missing" in codes
    client.post(f"/jobs/{j['id']}/commit")
    with Session(engine) as s:
        cfg = s.exec(select(PortIpConfigRow).order_by(PortIpConfigRow.id)).all()
        assert [(c.vlan, c.ip_address, c.prefix_len) for c in cfg] == [(100, "10.0.0.5", 24), (None, None, 24)]
    ip_items = [i for i in items(client, j["id"]) if i["item_type"] == "ip_missing"]
    assert sorted(i["target_field"] for i in ip_items) == ["ip_address", "vlan"]
    media = [i for i in items(client, j["id"]) if i["item_type"] == "media_missing"]
    assert {i["target_field"] for i in media} == {"media", "speed_z"}
    assert any("cable_mode" in i["note"] for i in media if i["target_field"] == "media")


def test_held_rows_resolve_after_epif_in_same_job_commit(client, engine):
    """Whole-job commit runs ePIF batches first, so a cable to a device the ePIF creates commits."""
    rack = make_rack(client)
    t = dtype(client, 1, name="1U")
    client.post("/devices", json={"host_name": "sw1", "rack_id": rack["id"], "device_type_id": t["id"],
                                  "position_u": 1})
    j = _job(client)
    cab = upload(client, j["id"], body(line(mid="E1", label="E1", z="new01", z_port="eth0"))).json()
    assert cab["rows"][0]["result"] == "held"
    epif = client.post(f"/jobs/{j['id']}/imports", params={"kind": "epif", "filename": "e.csv"}, headers=CSV,
                       content="ID,Name,Manufacturer,Model,Row,Rack,RU,PSU1,PSU2,S/N\n"
                               "10001,new01,Acme,1U,Row 1,R01,5,A1,B1,S1\n").json()
    assert epif["rows"][0]["result"] == "warning"
    c = client.post(f"/jobs/{j['id']}/commit").json()
    assert [x["kind"] for x in c["committed"]] == ["epif", "cable_matrix"]
    assert c["job"]["device_count"] == 1 and c["job"]["connection_count"] == 1
    assert len(c["resolved_item_ids"]) == 2  # epif_not_uploaded + cable_matrix_not_uploaded


def test_hard_delete_blocked_by_hops(client, engine, monkeypatch):
    from app.settings import get_settings
    monkeypatch.setattr(get_settings(), "hard_delete_enabled", True)
    _, ids = _env(client, engine)
    j = _job(client)
    upload(client, j["id"], body(line(mid="H1", label="H1", a_port="Eth1/1", z="srv1", hop1="pnl1:F1")))
    client.post(f"/jobs/{j['id']}/commit")
    r = client.delete(f"/devices/{ids['pnl1']}", params={"hard": "true"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "device_has_connections"


def test_readonly_cannot_commit(client, client_as, engine):
    _env(client, engine)
    j = _job(client)
    imp = upload(client, j["id"], body(line(mid="Q1", label="Q1"))).json()
    ro = client_as("read-only")
    assert ro.get(f"/jobs/{j['id']}/imports/{imp['id']}").status_code == 200
    assert ro.post(f"/jobs/{j['id']}/imports/{imp['id']}/commit").status_code == 403
    assert client_as("technician").post(f"/jobs/{j['id']}/imports/{imp['id']}/commit").status_code == 200


def test_parsers():
    from app.modules.jobs.cable_matrix import parse_length, parse_prefix, parse_speed
    assert parse_speed("100G") == 100_000 and parse_speed("25 Gbps") == 25_000 and parse_speed("1000M") == 1000
    assert parse_speed("100") is None and parse_speed("fast") is None and parse_speed("0.5M") is None
    assert parse_prefix("/24") == 24 and parse_prefix("255.255.255.0") == 24 and parse_prefix("255.0.255.0") is None
    assert str(parse_length("3.5m")) == "3.50" and parse_length("-1") is None and parse_length("x") is None
