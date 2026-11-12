"""Cable-matrix CSV intake onto an existing job (JOB_INTAKE.md §7, DEVICE_DATA_MODEL §7/§8, job-intake.md §4.2).

One row = one A↔Z connection + its cable + optional hops (Hop1-Hop7 as `panel:port`) + Z-side IP config.
- Committed only when BOTH endpoint ports resolve (live device by host name, then port by slot + name; a missing
  port is created as an endpoint port, like the quick entry in POST /connections). Otherwise the row is `held`:
  nothing is written, the staging row carries the open items.
- Hops, trail, label, media, IP and action are fill-later: the connection is still written and an open item is
  raised (unresolved_hop hop_N, missing_trail, missing_cable_label, media_missing, ip_missing, other).
- Conflicts skip the row, the batch continues: (port, lane) already connected (DB or earlier row, across both
  columns, lane 0 vs lane N on breakout ports), a hop (port, lane) already used, cable label taken (live, case-
  insensitive), matrix ID repeated or already imported, A = Z.
"""
import ipaddress
import json
import re
from decimal import Decimal, InvalidOperation

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.enums import CableType
from app.modules.audit.service import record_audit
from app.modules.connections import service as conn_svc
from app.modules.connections.models import (
    CABLE_MODES, CableRow, ConnectionHopRow, ConnectionRow, DevicePortRow, PortIpConfigRow,
)
from app.modules.devices.models import DeviceRow
from app.modules.directory.models import ProjectRow
from app.modules.jobs.epif import CommitAcc, RowEval, _items_for, formula_problem, parse_csv, reasons
from app.modules.jobs.models import ImportRowRow, JobImportRow
from app.modules.locations.models import HallRow, RackRow, RackRowRow

SIDES = ("a", "z")
HOPS = range(1, 8)
SIDE_PREFIXES = ("{s}_", "{s}_side_", "side_{s}_", "{s}_end_", "{s}")
SIDE_FIELDS = {
    "name": ("name", "host_name", "hostname", "device"),
    "row": ("row",),
    "rack": ("rack", "cabinet"),
    "ru": ("ru", "u"),
    "slot": ("slot", "slot_blade_card", "blade", "card"),
    "port": ("port", "port_name", "interface"),
    "lane": ("lane",),
    "xcvr_make": ("xcvr_make", "transceiver_make"),
    "xcvr_model": ("xcvr_model", "transceiver_model", "xcvr", "xcvr_make_model", "transceiver"),
    "connector": ("connector",),
    "speed": ("speed",),
}
IP_FIELDS = {
    "network": ("network",), "vlan": ("vlan",), "native_vlan": ("native_vlan",),
    "ip": ("ip", "ip_address"), "gateway": ("default_gateway", "gateway", "gw"),
    "mask": ("subnet_mask", "mask", "netmask", "prefix", "prefix_len"),
}
TOP_FIELDS = {
    "matrix_id": ("id", "matrix_id", "cable_id", "key"), "trail": ("trail",), "action": ("action",),
    "cable_type": ("cable_type", "type"), "cable_mode": ("cable_mode", "mode"),
    "cable_color": ("cable_color", "color", "colour"), "cable_length": ("cable_length", "length", "length_m"),
    "cable_label": ("cable_label", "label"), "tap": ("tap", "z_tap"), "dcreq": ("dcreq",),
}


def _aliases() -> dict:
    a = {}
    for canon, names in TOP_FIELDS.items():
        for n in names:
            a[n] = canon
    for f, names in IP_FIELDS.items():  # IP config is on the Z side (field notes); A-side IP is not modeled
        for n in names:
            a[n] = f"ip_{f}"
            a[f"z_{n}"] = f"ip_{f}"
    for s in SIDES:
        for f, names in SIDE_FIELDS.items():
            for n in names:
                for pre in SIDE_PREFIXES:
                    a[pre.format(s=s) + n] = f"{s}_{f}"
    for i in HOPS:
        for n in (f"hop{i}", f"hop_{i}", f"a_hop{i}", f"a_hop_{i}"):
            a[n] = f"hop{i}"
    return a


ALIASES = _aliases()
REQUIRED = (("a_name", "A Name"), ("a_port", "A Port"), ("z_name", "Z Name"), ("z_port", "Z Port"))
FIELD_MAX = {"matrix_id": 64, "trail": 128, "cable_label": 64, "cable_color": 32, "a_slot": 64, "z_slot": 64,
             "a_port": 64, "z_port": 64, "a_xcvr_make": 64, "z_xcvr_make": 64, "a_xcvr_model": 64,
             "z_xcvr_model": 64, "a_connector": 32, "z_connector": 32, "ip_network": 64}
_SPEED = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([mgt])(?:b(?:ps|it/s|/s)?|e)?\s*$", re.I)
TRUTHY = {"y", "yes", "true", "1", "tap", "x"}
MEDIA = ("cable_type", "cable_mode", "color", "length_m")


def parse(text: str, max_rows: int) -> list[tuple[int, dict]]:
    return parse_csv(text, max_rows, ALIASES, REQUIRED, "The cable matrix")


def parse_speed(raw: str) -> int | None:
    m = _SPEED.match(raw)
    if not m:
        return None
    mbps = float(m.group(1)) * {"m": 1, "g": 1000, "t": 1_000_000}[m.group(2).lower()]
    return int(mbps) if mbps >= 1 and mbps == int(mbps) else None


def parse_length(raw: str) -> Decimal | None:
    v = raw.strip().lower().removesuffix("m").strip()
    try:
        d = Decimal(v)
    except InvalidOperation:
        return None
    return d.quantize(Decimal("0.01")) if Decimal("0") < d < Decimal("1000000") else None


def parse_prefix(raw: str) -> int | None:
    v = raw.strip().lstrip("/")
    if v.isdigit():
        n = int(v)
        return n if 0 <= n <= 128 else None
    try:
        return ipaddress.IPv4Network(f"0.0.0.0/{v}").prefixlen
    except ValueError:
        return None


def parse_vlan(raw: str) -> int | None:
    return int(raw) if raw.strip().isdigit() and 1 <= int(raw) <= 4094 else None


def parse_ip(raw: str) -> str | None:
    try:
        return str(ipaddress.ip_address(raw.strip()))
    except ValueError:
        return None


# ---------------------------------------------------------------- validate
class Context:
    """Lookups preloaded once per file (live devices by name with their cabinet path, cable labels / matrix IDs);
    ports and occupancy are read per device / port and cached."""

    def __init__(self, session: Session, job: ProjectRow, dcreq: str):
        self.session, self.job, self.dcreq = session, job, dcreq
        rows = session.exec(
            select(DeviceRow, RackRow.name, RackRowRow.name, HallRow.name)
            .join(RackRow, RackRow.id == DeviceRow.rack_id, isouter=True)
            .join(RackRowRow, RackRowRow.id == RackRow.row_id, isouter=True)
            .join(HallRow, HallRow.id == RackRow.hall_id, isouter=True)
            .where(DeviceRow.deleted_at.is_(None))).all()
        self.devices: dict[str, list] = {}
        for d, rack, row, hall in rows:
            self.devices.setdefault(d.host_name.strip().lower(), []).append((d, rack, row, hall))
        self.labels = {lbl.lower() for lbl in session.exec(select(CableRow.label).where(
            CableRow.label.is_not(None), CableRow.status != "removed")).all()}
        self.external_ids = set(session.exec(select(CableRow.external_id).where(
            CableRow.external_id.is_not(None))).all())
        self._ports: dict[int, dict] = {}
        # in-file tracking
        self.seen_ids: dict[str, int] = {}
        self.seen_labels: dict[str, int] = {}
        self.port_lanes: dict[tuple, dict[int, int]] = {}  # port key -> {lane: row_number}
        self.hop_slots: dict[tuple[int, int], int] = {}

    def ports(self, device_id: int) -> dict:
        if device_id not in self._ports:
            self._ports[device_id] = {
                ((p.slot or ""), p.name.lower()): p for p in self.session.exec(select(DevicePortRow).where(
                    DevicePortRow.device_id == device_id, DevicePortRow.deleted_at.is_(None))).all()}
        return self._ports[device_id]


def _device(ctx: Context, name: str, row: str | None, rack: str | None):
    """Resolve a live device by host name; Row/Rack narrow duplicates. Returns (device, (rack, row)) or None."""
    found = ctx.devices.get(name.lower(), [])
    if len(found) > 1 and (row or rack):
        narrowed = [f for f in found if (not rack or (f[1] or "").lower() == rack.lower())
                    and (not row or (f[2] or "").lower() == row.lower())]
        found = narrowed or found
    if not found:
        return None, "missing"
    if len(found) > 1:
        where = ", ".join(sorted(f"{h or '?'}/{r or '?'}/{k or '?'}" for _, k, r, h in found))
        return None, f"({where})"
    d, rk, rw, _ = found[0]
    return d, (rk, rw)


def _side(ctx: Context, ev: RowEval, s: str) -> dict | None:
    c, S = ev.cells, s.upper()
    name, port_name, slot = c.get(f"{s}_name"), c.get(f"{s}_port"), c.get(f"{s}_slot")
    out = {"slot": slot, "port_name": port_name, "lane": None, "attrs": {}}
    if not name:
        ev.add("held", "missing_hostname", f"{S} Name is empty", f"{s}_name", "missing_hostname", f"host_name_{s}")
        return None
    dev, info = _device(ctx, name, c.get(f"{s}_row"), c.get(f"{s}_rack"))
    if dev is None and info == "missing":
        ev.add("held", "unresolved_device", f"No live device named '{name}' ({S} end)", f"{s}_name",
               "missing_hostname", f"host_name_{s}")
        return None
    if dev is None:
        ev.add("held", "ambiguous_device", f"'{name}' matches several devices {info} ({S} end); add Row and Rack",
               f"{s}_rack", "unresolved_cabinet", f"rack_{s}")
        return None
    rack_name, row_name = info
    for f, actual, label in ((f"{s}_rack", rack_name, "Rack"), (f"{s}_row", row_name, "Row")):
        given = c.get(f)
        if given and (actual or "").lower() != given.lower():
            ev.add("warning", "cabinet_mismatch", f"{S} {label} says '{given}' but {dev.host_name} is in "
                   f"'{actual or 'no cabinet'}'", f, "unresolved_cabinet", f"rack_{s}")
            break
    ru = c.get(f"{s}_ru")
    if ru and dev.position_u is not None and ru.strip() != str(dev.position_u):
        ev.add("warning", "ru_mismatch", f"{S} RU says {ru} but {dev.host_name} is at U{dev.position_u}", f"{s}_ru",
               "other", f"position_u_{s}")
    out.update(device_id=dev.id, host=dev.host_name)
    if not port_name:
        ev.add("held", "missing_port", f"{S} Port is empty", f"{s}_port", "missing_port", f"port_{s}")
        return None
    port = ctx.ports(dev.id).get(((slot or ""), port_name.lower()))
    if port is None:
        ev.add("info", "port_created", f"{S} port {port_name} doesn't exist on {dev.host_name}; it will be created",
               f"{s}_port")
        out["key"] = ("new", dev.id, slot or "", port_name.lower())
        out["lanes"] = None
    else:
        if port.role != "endpoint":
            ev.add("held", "port_not_endpoint", f"{S} port {port.name} on {dev.host_name} is a panel {port.role} port; "
                   "put panels in Hop1-Hop7", f"{s}_port", "other", f"port_{s}")
            return None
        out["port_id"], out["key"], out["lanes"] = port.id, ("port", port.id), port.lanes
    lane_raw = c.get(f"{s}_lane")
    if lane_raw:
        if lane_raw.isdigit():
            out["lane"] = int(lane_raw)
        else:
            ev.add("warning", "lane_invalid", f"{S} Lane '{lane_raw}' isn't a whole number; lane 0 is used",
                   f"{s}_lane", "other", f"lane_{s}")
    # transceiver / connector / speed (fill empty port fields only)
    attrs = {}
    for f, col in (("xcvr_make", "transceiver_make"), ("xcvr_model", "transceiver_model"), ("connector", "connector")):
        if c.get(f"{s}_{f}"):
            attrs[col] = c[f"{s}_{f}"]
    if c.get(f"{s}_speed"):
        sp = parse_speed(c[f"{s}_speed"])
        if sp is None:
            ev.add("warning", "speed_unparsed", f"{S} Speed '{c[f'{s}_speed']}' isn't like 25G or 100 Gbps",
                   f"{s}_speed", "media_missing", f"speed_{s}")
        else:
            attrs["speed_mbps"] = sp
    if s == "z" and (c.get("tap") or "").strip().lower() in TRUTHY:
        attrs["kind"] = "tap"
    if port is not None:
        for col, v in list(attrs.items()):
            cur = getattr(port, col)
            if cur is not None and str(cur) != str(v):
                ev.add("info", "port_value_kept", f"{S} port {port.name} already has {col} = {cur}; kept", f"{s}_{col}")
                attrs.pop(col)
            elif cur is not None:
                attrs.pop(col)
    out["attrs"] = attrs
    return out


def _hop(ctx: Context, ev: RowEval, i: int, raw: str):
    if ":" not in raw:
        ev.add("warning", "hop_unresolved", f"Hop{i} '{raw}' must be panel:port (e.g. MPO-PNL-03:F2)", f"hop{i}",
               "unresolved_hop", f"hop_{i}")
        return None
    panel, port_name = (x.strip() for x in raw.rsplit(":", 1))
    found = ctx.devices.get(panel.lower(), [])
    if len(found) != 1:
        why = "no live device" if not found else "several devices"
        ev.add("warning", "hop_unresolved", f"Hop{i} '{raw}': {why} named '{panel}'", f"hop{i}", "unresolved_hop",
               f"hop_{i}")
        return None
    dev = found[0][0]
    port = ctx.ports(dev.id).get(("", port_name.lower())) or next(
        (p for (_, n), p in ctx.ports(dev.id).items() if n == port_name.lower()), None)
    if port is None:
        ev.add("warning", "hop_unresolved", f"Hop{i} '{raw}': {panel} has no port '{port_name}'", f"hop{i}",
               "unresolved_hop", f"hop_{i}")
        return None
    if port.role not in ("front", "rear"):
        ev.add("warning", "hop_unresolved", f"Hop{i} '{raw}': {port.name} on {panel} isn't a panel front/rear port",
               f"hop{i}", "unresolved_hop", f"hop_{i}")
        return None
    return {"seq": i, "port_id": port.id, "role": port.role, "rear_port_id": port.rear_port_id,
            "rear_position": port.rear_position, "lane": 0, "text": raw}


def _occupied(ctx: Context, key: tuple, lane: int, breakout: bool) -> int | None:
    """Row number of an earlier row in this file holding (port, lane) (lane 0 vs N on breakout ports)."""
    used = ctx.port_lanes.get(key, {})
    if not used:
        return None
    if not breakout:
        return used.get(lane)
    if lane == 0:
        return next(iter(used.values()))
    return used.get(lane) or used.get(0)


def evaluate(ctx: Context, row_number: int, cells: dict) -> RowEval:
    ev = RowEval(row_number, cells)
    for k, v in cells.items():
        if formula_problem(v):
            ev.add("warning", "formula_text", f"{k} starts like a spreadsheet formula; stored as text", k)
        if k in FIELD_MAX and len(v) > FIELD_MAX[k]:
            cells[k] = v[:FIELD_MAX[k]]
            ev.add("warning", "value_truncated", f"{k} is longer than {FIELD_MAX[k]} characters; it was cut", k)
    p = ev.plan
    # ID (matrix key -> cables.external_id)
    mid = cells.get("matrix_id")
    p["matrix_id"] = mid
    if mid is None:
        ev.add("warning", "matrix_id_missing", "No ID on this row", "matrix_id", "other", "external_id", "cable")
    elif mid in ctx.seen_ids:
        ev.add("conflict", "duplicate_matrix_id", f"ID {mid} is repeated in this file (row {ctx.seen_ids[mid]})",
               "matrix_id", "other", "external_id")
    elif mid in ctx.external_ids:
        ev.add("conflict", "matrix_id_already_imported", f"ID {mid} is already on a cable", "matrix_id", "other",
               "external_id")
    if mid:
        ctx.seen_ids.setdefault(mid, row_number)
    # Action
    action = (cells.get("action") or "").strip().lower()
    if not action:
        action = "add"
        ev.add("warning", "action_defaulted", "No action given; treated as Add", "action")
    p["action"] = action
    if action in ("remove", "move"):
        ev.add("held", "action_not_applied", f"{action.title()} rows aren't applied by job intake v1; change the "
               "connection from its page", "action", "other", "action")
    elif action != "add":
        ev.add("held", "action_unknown", "Action must be Add, Remove or Move", "action", "other", "action")

    # Cable fields (fill-later)
    label = cells.get("cable_label")
    p["label"] = label
    if label is None:
        ev.add("warning", "missing_cable_label", "No cable label", "cable_label", "missing_cable_label", "label",
               "cable")
    else:
        if label.lower() in ctx.labels:
            ev.add("conflict", "cable_label_conflict", f"Cable label '{label}' is already on a live cable",
                   "cable_label", "other", "label")
        elif label.lower() in ctx.seen_labels:
            ev.add("conflict", "cable_label_conflict", f"Cable label '{label}' is repeated in this file (row "
                   f"{ctx.seen_labels[label.lower()]})", "cable_label", "other", "label")
        ctx.seen_labels.setdefault(label.lower(), row_number)
    p["trail"] = cells.get("trail")
    if p["trail"] is None:
        ev.add("warning", "missing_trail", "No trail", "trail", "missing_trail", "trail", "cable")
    missing_media = []
    ct = cells.get("cable_type")
    p["cable_type"] = next((t.value for t in CableType if ct and t.value.lower() == ct.strip().lower()), None)
    if ct and p["cable_type"] is None:
        ev.add("info", "cable_type_unknown", f"Cable type '{ct}' isn't one of {', '.join(t.value for t in CableType)}; "
               "not stored", "cable_type")
    cm = cells.get("cable_mode")
    p["cable_mode"] = cm.strip().lower() if cm and cm.strip().lower() in CABLE_MODES else None
    if cm and p["cable_mode"] is None:
        ev.add("info", "cable_mode_unknown", f"Cable mode '{cm}' isn't one of {', '.join(CABLE_MODES)}; not stored",
               "cable_mode")
    p["color"] = cells.get("cable_color")
    ln = cells.get("cable_length")
    p["length_m"] = parse_length(ln) if ln else None
    if ln and p["length_m"] is None:
        ev.add("info", "length_unparsed", f"Length '{ln}' isn't a number of metres; not stored", "cable_length")
    for f in MEDIA:
        if p.get(f) is None:
            missing_media.append(f)
    if p["cable_type"] is None or p["cable_mode"] is None:
        ev.add("warning", "media_missing", f"Cable details missing: {', '.join(missing_media)}", "cable_type",
               "media_missing", "media", "cable")

    # IP config (Z port)
    ip = {}
    for f, parser, col in (("vlan", parse_vlan, "vlan"), ("native_vlan", parse_vlan, "native_vlan"),
                           ("ip", parse_ip, "ip_address"), ("gateway", parse_ip, "default_gateway"),
                           ("mask", parse_prefix, "prefix_len")):
        raw = cells.get(f"ip_{f}")
        if raw:
            v = parser(raw)
            if v is None:
                ev.add("warning", "ip_invalid", f"{f.replace('_', ' ').title()} '{raw}' isn't valid; not stored",
                       f"ip_{f}", "ip_missing", col)
            else:
                ip[col] = v
    if cells.get("ip_network"):
        ip["network"] = cells["ip_network"]
    p["ip"] = ip

    # Ends
    ends = {s: _side(ctx, ev, s) for s in SIDES}
    p["ends"] = ends
    # Hops (fill-later; a hop that is named but doesn't resolve is an open item, the connection is still written)
    hops = []
    for i in HOPS:
        raw = cells.get(f"hop{i}")
        if raw:
            h = _hop(ctx, ev, i, raw)
            if h:
                hops.append(h)
    # rear hops carry the MPO position of the front hop that maps to them
    for h in hops:
        if h["role"] == "rear":
            front = next((f for f in hops if f["role"] == "front" and f["rear_port_id"] == h["port_id"]), None)
            h["lane"] = front["rear_position"] if front else 0
    p["hops"] = hops
    if any(e is None for e in ends.values()):
        return ev  # held: no occupancy checks without both ends

    a, z = ends["a"], ends["z"]
    if a["key"] == z["key"]:
        ev.add("conflict", "self_connection", "A and Z are the same port", "z_port", "other", "port_z")
        return ev
    # lanes: blank = derived from a panel front hop on a breakout port, else 0
    front = next((h for h in hops if h["role"] == "front"), None)
    for e, S in ((a, "A"), (z, "Z")):
        breakout = (e.get("lanes") or 0) > 1
        if e["lane"] is None:
            e["lane"] = front["rear_position"] if breakout and front else 0
        if e["lane"] > 0 and (not e.get("lanes") or e["lane"] > e["lanes"]):
            ev.add("conflict", "lane_out_of_range", f"{S} lane {e['lane']} is more than the port's breakout lanes "
                   f"({e.get('lanes') or 'none'})", f"{S.lower()}_lane", "other", f"lane_{S.lower()}")
            continue
        holder = conn_svc.port_in_use(ctx.session, e["port_id"], e["lane"], breakout=breakout) \
            if e.get("port_id") else None
        if holder is not None:
            ev.add("conflict", "port_in_use", f"{S} port {e['port_name']} on {e['host']}"
                   f"{' lane ' + str(e['lane']) if e['lane'] else ''} already has connection {holder}",
                   f"{S.lower()}_port", "other", f"port_{S.lower()}")
            continue
        other = _occupied(ctx, e["key"], e["lane"], breakout)
        if other is not None:
            ev.add("conflict", "port_in_use", f"{S} port {e['port_name']} on {e['host']} is already used by row "
                   f"{other} of this file", f"{S.lower()}_port", "other", f"port_{S.lower()}")
    for h in hops:
        slot = (h["port_id"], h["lane"])
        taken = ctx.session.exec(select(ConnectionHopRow.connection_id).where(
            ConnectionHopRow.port_id == h["port_id"], ConnectionHopRow.lane == h["lane"],
            ConnectionHopRow.is_active.is_(True))).first()
        if taken is not None:
            ev.add("conflict", "hop_in_use", f"Hop{h['seq']} {h['text']} is already used by connection {taken}",
                   f"hop{h['seq']}", "other", f"hop_{h['seq']}")
        elif slot in ctx.hop_slots:
            ev.add("conflict", "hop_in_use", f"Hop{h['seq']} {h['text']} is already used by row "
                   f"{ctx.hop_slots[slot]} of this file", f"hop{h['seq']}", "other", f"hop_{h['seq']}")
    if ev.result not in ("conflict", "held"):
        for e in (a, z):
            ctx.port_lanes.setdefault(e["key"], {}).setdefault(e["lane"], row_number)
        for h in hops:
            ctx.hop_slots.setdefault((h["port_id"], h["lane"]), row_number)
    return ev


def evaluate_all(session: Session, job: ProjectRow, dcreq: str, rows: list[tuple[int, dict]]) -> list[RowEval]:
    ctx = Context(session, job, dcreq)
    return [evaluate(ctx, n, dict(cells)) for n, cells in rows]


# ---------------------------------------------------------------- commit
def _port(session: Session, e: dict, created: dict) -> DevicePortRow:
    if e.get("port_id"):
        port = session.get(DevicePortRow, e["port_id"])
    else:
        key = e["key"]
        port = created.get(key)
        if port is None:
            port = DevicePortRow(device_id=e["device_id"], slot=e["slot"], name=e["port_name"], role="endpoint")
            session.add(port)
            session.flush()
            created[key] = port
    for col, v in e["attrs"].items():
        if getattr(port, col) is None:
            setattr(port, col, v)
    session.add(port)
    return port


def _write(session: Session, job: ProjectRow, p: dict, cs, created_ports: dict):
    """Write one row in a savepoint. Returns (connection, cable, None) or (None, None, conflict tuple)."""
    sp = session.begin_nested()
    try:
        a, z = p["ends"]["a"], p["ends"]["z"]
        pa, pz = _port(session, a, created_ports), _port(session, z, created_ports)
        conn_svc.lock_ports(session, [pa.id, pz.id])
        for e, port, S in ((a, pa, "A"), (z, pz, "Z")):
            holder = conn_svc.port_in_use(session, port.id, e["lane"], breakout=(port.lanes or 0) > 1)
            if holder is not None:
                sp.rollback()
                return None, None, ("conflict", "port_in_use", f"{S} port {port.name} already has connection "
                                    f"{holder}", f"{S.lower()}_port", "other", f"port_{S.lower()}")
        cable = CableRow(label=p["label"], cable_type=p["cable_type"], cable_mode=p["cable_mode"], color=p["color"],
                         length_m=p["length_m"], trail=p["trail"], external_id=p["matrix_id"], status="active",
                         project_id=job.id)
        session.add(cable)
        session.flush()
        ends = sorted(((pa.id, a["lane"]), (pz.id, z["lane"])))  # canonical order; lanes travel with ports
        conn = ConnectionRow(port1_id=ends[0][0], port1_lane=ends[0][1], port2_id=ends[1][0], port2_lane=ends[1][1],
                             cable_id=cable.id, status="active", action="add", change_set_id=cs.id)
        session.add(conn)
        session.flush()
        for h in p["hops"]:
            session.add(ConnectionHopRow(connection_id=conn.id, seq=h["seq"], port_id=h["port_id"], lane=h["lane"]))
        if p["ip"]:
            session.add(PortIpConfigRow(port_id=pz.id, **p["ip"]))
        session.flush()
        sp.commit()
        return conn, cable, None
    except IntegrityError:
        sp.rollback()
        return None, None, ("conflict", "write_conflict", "The database refused this row (port, hop, label or ID "
                            "taken at the same time)", "a_port", "other", "port_a")


def commit_rows(session: Session, job: ProjectRow, dcreq: str, imp: JobImportRow, rows: list[ImportRowRow], cs,
                who: str | None, acc: CommitAcc) -> None:
    evals = evaluate_all(session, job, dcreq, [(r.row_number, json.loads(r.raw_json)) for r in rows])
    created_ports: dict = {}
    for r, ev in zip(rows, evals):
        p, res = ev.plan, ev.result
        conn = cable = None
        if res in ("ready", "warning"):
            conn, cable, problem = _write(session, job, p, cs, created_ports)
            if problem:
                ev.add(*problem)
                res = "conflict"
        a = (p.get("ends") or {}).get("a") or {}
        base = {"import_id": imp.id, "kind": imp.kind, "row_number": r.row_number, "epif_id": None,
                "matrix_id": p.get("matrix_id"), "hostname": a.get("host") or ev.cells.get("a_name"),
                "a": _txt(ev.cells, "a"), "z": _txt(ev.cells, "z")}
        if res == "conflict":
            r.result = "skipped"
            acc.skipped.append({**base, "reasons": reasons(ev, "conflict")})
            _items_for(session, job.id, [m for m in ev.messages if m["level"] == "conflict"], cs.id, {}, r.id, who,
                       acc.created, source="cable_matrix")
        elif res == "held":
            r.result = "held"
            acc.held.append({**base, "reasons": reasons(ev, "held")})
            _items_for(session, job.id, ev.messages, cs.id, {}, r.id, who, acc.created, source="cable_matrix")
        else:
            r.result, r.connection_id, r.cable_id = "committed", conn.id, cable.id
            acc.committed.append({**base, "connection_id": conn.id, "cable_id": cable.id,
                                  "cable_label": cable.label})
            _items_for(session, job.id, ev.messages, cs.id, {"connection_id": conn.id}, r.id, who, acc.created,
                       source="cable_matrix", targets={"cable": {"cable_id": cable.id}})
            out = conn_svc.load_connection(session, conn.id)
            record_audit(session, None, "connection.create", "connection", conn.id, after={
                "a": f"{out['a']['host_name']}:{out['a']['port_name']}",
                "b": f"{out['b']['host_name']}:{out['b']['port_name']}",
                "a_port_id": out["a"]["port_id"], "b_port_id": out["b"]["port_id"],
                "lanes": [conn.port1_lane, conn.port2_lane], "hops": [h["text"] for h in p["hops"]],
                "cable": {"id": cable.id, "label": cable.label, "trail": cable.trail, "external_id": cable.external_id},
                "job_id": job.id, "change_set_id": cs.id}, import_batch_id=f"job_import:{imp.id}")
        if res != "conflict":
            acc.warn(ev, imp, base["hostname"])
        r.messages_json = json.dumps(ev.messages)
        session.add(r)


def _txt(cells: dict, side: str) -> str | None:
    from app.modules.jobs.epif import _end_text
    return _end_text(cells, side)


def connection_counts(session: Session, ids: list[int]) -> dict[int, int]:
    """Non-removed connections whose cable belongs to the job (cables.project_id)."""
    if not ids:
        return {}
    rows = session.exec(select(CableRow.project_id, func.count(ConnectionRow.id))
                        .join(ConnectionRow, ConnectionRow.cable_id == CableRow.id)
                        .where(CableRow.project_id.in_(ids), ConnectionRow.status != "removed")
                        .group_by(CableRow.project_id)).all()
    return dict(rows)
