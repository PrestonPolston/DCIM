"""Seed a demo data center (re-runnable, idempotent).

    cd apps/api && python scripts/seed_demo.py            # create what is missing
    cd apps/api && python scripts/seed_demo.py --reseed   # wipe the demo data, then seed again

Uses the database from DCIM_DATABASE_URL (same as the app; run `alembic upgrade head` first).
Refuses --wipe/--reseed when DCIM_ENV=prod unless --force, and never creates the fixed-password
demo users in prod (DEV-ONLY logins, see README "Demo data").

Layout ("Demo Hall", aisle_axis=y, odd_side=low in site "Demo DC"): 30 rows x 14 cabinets (53U), R01-C01 .. R30-C14.
Two banks with a center aisle: odd rows in the left bank (x 0..13, fronts face E toward the aisle),
even rows in the right bank (x 17..30, fronts face W). Rows 2k-1 and 2k form facing pair k at
pos_y = 2(k-1) (one empty grid row between pairs). C01 sits next to the aisle in both banks.
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, or_  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

import app.models  # noqa: E402,F401
from app.modules.auth.models import UserRow  # noqa: E402
from app.modules.auth.passwords import hash_password  # noqa: E402
from app.modules.device_types.models import DeviceTypeProfileRow, DeviceTypeRow  # noqa: E402
from app.modules.connections.models import CableRow, ConnectionRow, DevicePortRow  # noqa: E402
from app.modules.devices import lifecycle  # noqa: E402
from app.modules.devices.models import DeviceRow  # noqa: E402
from app.modules.history.models import (  # noqa: E402
    DevicePlacementHistoryRow, DeviceStatusHistoryRow,
)
from app.modules.history.service import new_change_set  # noqa: E402
from app.modules.locations.models import HallRow, RackRow, RackRowRow, SiteRow  # noqa: E402
from app.settings import get_settings  # noqa: E402

SITE, HALL = "Demo DC", "Demo Hall"
ROWS, CABINETS, U = 30, 14, 53  # standard cabinet: 53 RU
AISLE_GAP = 3  # empty grid columns between the banks
RIGHT_X = CABINETS + AISLE_GAP  # 17

# DEV-ONLY demo logins (documented in README); never created when DCIM_ENV=prod
DEMO_USERS = [
    ("admin@demo.local", "admin", "Demo Admin", "dcim-demo-Alpha-2026"),
    ("tech@demo.local", "technician", "Demo Technician", "dcim-demo-Bravo-2026"),
    ("readonly@demo.local", "read-only", "Demo Read-only", "dcim-demo-Charlie-2026"),
]

# (manufacturer, model, u_height, full_depth, width_mm, height_mm, depth_mm, ports)
DEVICE_TYPES = [
    ("Dell", "PowerEdge R660", 1, True, 482.6, 42.8, 822.9, 4),
    ("Dell", "PowerEdge R760", 2, True, 482.6, 86.8, 772.1, 4),
    ("HPE", "ProLiant DL360 Gen11", 1, True, 434.6, 42.9, 747.5, 4),
    ("HPE", "ProLiant DL380 Gen11", 2, True, 445.4, 87.5, 734.3, 4),
    ("Cisco", "Nexus 93180YC-FX3", 1, False, 439.0, 43.9, 571.5, 54),
    ("Arista", "7050SX3-48YC8", 1, False, 440.0, 43.5, 482.6, 56),
    ("Arista", "7280R3-48YC6", 2, True, 440.0, 88.0, 609.6, 54),
    ("Juniper", "QFX5120-48Y", 1, False, 441.0, 43.6, 482.6, 56),
    ("Cisco", "Catalyst 9500-48Y4C", 1, False, 445.0, 43.9, 469.9, 52),
    ("Juniper", "MX304", 4, True, 442.0, 175.0, 609.6, 48),
    ("Panduit", "CPP24WBLY 24-port Patch Panel", 1, False, 482.6, 44.0, 101.6, 24),
    ("APC", "AP7900B Rack PDU 1U", 1, False, 482.6, 44.5, 228.0, 8),
    ("NetApp", "DS224C Storage Shelf", 2, True, 447.0, 85.3, 543.0, 0),
]

# Item 46: every demo profile is complete and published (asset type, AC/DC, 19-inch mounting, weight, DEMO image)
ASSET_TYPES = {"PowerEdge R660": "server", "PowerEdge R760": "server", "ProLiant DL360 Gen11": "server",
               "ProLiant DL380 Gen11": "server", "Nexus 93180YC-FX3": "switch", "7050SX3-48YC8": "switch",
               "7280R3-48YC6": "switch", "QFX5120-48Y": "switch", "Catalyst 9500-48Y4C": "switch",
               "MX304": "router", "CPP24WBLY 24-port Patch Panel": "patch_panel", "AP7900B Rack PDU 1U": "pdu",
               "DS224C Storage Shelf": "storage"}
WEIGHT_KG = {"PowerEdge R660": 18.5, "PowerEdge R760": 28.6, "ProLiant DL360 Gen11": 16.3,
             "ProLiant DL380 Gen11": 25.4, "Nexus 93180YC-FX3": 9.0, "7050SX3-48YC8": 9.5, "7280R3-48YC6": 15.0,
             "QFX5120-48Y": 9.8, "Catalyst 9500-48Y4C": 10.5, "MX304": 45.4,
             "CPP24WBLY 24-port Patch Panel": 1.4, "AP7900B Rack PDU 1U": 2.3, "DS224C Storage Shelf": 23.7}


def demo_front_image(mfr: str, model: str, u: int, face: str = "front") -> bytes:
    """A generated placeholder image, clearly labeled DEMO (not a vendor photo)."""
    import io

    from PIL import Image, ImageDraw, ImageFont
    w, h = 960, 40 * u
    img = Image.new("RGB", (w, h), (52, 58, 64) if face == "front" else (33, 37, 41))
    draw = ImageDraw.Draw(img)
    draw.rectangle([2, 2, w - 3, h - 3], outline=(173, 181, 189), width=2)
    for x in (12, w - 24):  # rack ears
        draw.rectangle([x, 6, x + 12, h - 7], fill=(108, 117, 125))
    font = ImageFont.load_default(size=min(22, h - 14))
    label = f"DEMO  {mfr} {model}  ({u}U)" + ("  REAR" if face == "rear" else "")
    draw.text((40, h // 2), label, fill=(248, 249, 250), font=font, anchor="lm")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


# cabinet -> [(host, model, position_u, status, face)]; models refer to DEVICE_TYPES names
def _cabinet(prefix, layout):
    return [(f"{prefix}-{name}", model, u, status, face) for name, model, u, status, face in layout]


STD = [
    ("pdu-a", "AP7900B Rack PDU 1U", 1, "active", "rear"),
    ("pp-01", "CPP24WBLY 24-port Patch Panel", 53, "active", "front"),
    ("leaf-01", "Nexus 93180YC-FX3", 52, "active", "front"),
    ("leaf-02", "7050SX3-48YC8", 51, "active", "front"),
    ("srv-01", "PowerEdge R660", 2, "active", "front"),
    ("srv-02", "PowerEdge R660", 3, "active", "front"),
    ("srv-03", "PowerEdge R760", 4, "active", "front"),
    ("srv-04", "ProLiant DL380 Gen11", 6, "install", "front"),
    ("srv-05", "ProLiant DL360 Gen11", 8, "active", "front"),
    ("nas-01", "DS224C Storage Shelf", 10, "active", "front"),
]
SPINE = [
    ("pp-01", "CPP24WBLY 24-port Patch Panel", 53, "active", "front"),
    ("spine-01", "7280R3-48YC6", 38, "active", "front"),
    ("spine-02", "7280R3-48YC6", 35, "active", "front"),
    ("core-01", "Catalyst 9500-48Y4C", 33, "install", "front"),
    ("edge-01", "MX304", 20, "active", "front"),
    ("tor-01", "QFX5120-48Y", 30, "active", "front"),
    ("pdu-a", "AP7900B Rack PDU 1U", 1, "active", "rear"),
]
PLACED = {
    "R01-C01": _cabinet("r01c01", STD),
    "R02-C01": _cabinet("r02c01", STD),
    "R03-C05": _cabinet("r03c05", STD[:7]),
    "R04-C07": _cabinet("r04c07", SPINE),
    "R10-C14": _cabinet("r10c14", STD[:6]),
}
# not in a cabinet: decommissioned (must be unracked) and stock waiting to be installed
UNPLACED = [
    *[(f"old-srv-{i:02d}", "PowerEdge R660", "decom") for i in range(1, 7)],
    ("old-sw-01", "Nexus 93180YC-FX3", "decom"),
    ("old-nas-01", "DS224C Storage Shelf", "decom"),
    *[(f"spare-srv-{i:02d}", "ProLiant DL360 Gen11", "install") for i in range(1, 5)],
]


def cabinet_layout(row: int, cab: int) -> tuple[int, int, str]:
    """(pos_x, pos_y, orientation) for cabinet `cab` (1-based) in row `row` (1-based)."""
    pair = (row + 1) // 2  # 1..15
    y = 2 * (pair - 1)
    if row % 2:  # odd: left bank, C01 next to the aisle
        return CABINETS - cab, y, "E"
    return RIGHT_X + cab - 1, y, "W"


def row_layout(row: int) -> tuple[int, int, str]:
    pair = (row + 1) // 2
    return (0 if row % 2 else RIGHT_X), 2 * (pair - 1), ("E" if row % 2 else "W")


def _get(session, model, **keys):
    return session.exec(select(model).filter_by(**keys)).first()


def _demo_links() -> list[tuple[str, str, str, str, str]]:
    """(a_host, a_port, b_host, b_port, cable_type): server NICs to leaves (RJ45/LC), leaf pairs (DAC),
    leaf uplinks to the spine cabinet (LC, cross-cabinet), and a few links on decom/install gear."""
    links = []
    std = [cab for cab, devs in PLACED.items() if any(h.endswith("leaf-01") for h, *_ in devs)]
    for n, cab in enumerate(std, start=1):
        hosts = {h.split("-", 1)[1]: h for h, *_ in PLACED[cab]}
        leaf1, leaf2 = hosts.get("leaf-01"), hosts.get("leaf-02")
        for k in range(1, 6):
            srv = hosts.get(f"srv-{k:02d}")
            if srv:
                links.append((srv, "eth0", leaf1, f"Eth1/{k}", "RJ45"))
                if leaf2:
                    links.append((srv, "eth1", leaf2, f"Ethernet{k}", "LC"))
        if leaf2:
            links.append((leaf1, "Eth1/49", leaf2, "Ethernet49", "DAC"))
            links.append((leaf2, "Ethernet53", "r04c07-spine-02", f"Ethernet{n}", "LC"))
        links.append((leaf1, "Eth1/53", "r04c07-spine-01", f"Ethernet{n}", "LC"))
    links += [
        ("r04c07-spine-01", "Ethernet47", "r04c07-spine-02", "Ethernet47", "DAC"),
        ("r04c07-core-01", "Hu1/0/1", "r04c07-edge-01", "et-0/0/0", "LC"),  # core-01 is install
        ("old-srv-01", "eth0", "r01c01-leaf-01", "Eth1/40", "RJ45"),      # decom end, kept for tracing
        ("old-srv-02", "eth0", "old-sw-01", "Eth1/1", "RJ45"),            # both ends decom
    ]
    return links


def _demo_host_names() -> set[str]:
    names = {h for devs in PLACED.values() for h, *_ in devs}
    return names | {h for h, *_ in UNPLACED}


def wipe(session: Session) -> None:
    hosts = _demo_host_names()
    device_ids = list(session.exec(select(DeviceRow.id).where(DeviceRow.host_name.in_(hosts))).all())
    site = _get(session, SiteRow, name=SITE)
    hall = _get(session, HallRow, site_id=site.id, name=HALL) if site else None
    row_ids = list(session.exec(select(RackRowRow.id).where(RackRowRow.hall_id == hall.id)).all()) if hall else []
    rack_ids = list(session.exec(select(RackRow.id).where(RackRow.row_id.in_(row_ids))).all()) if row_ids else []
    if rack_ids:  # non-demo devices in demo cabinets would block the wipe; unrack them by decom first
        device_ids += list(session.exec(select(DeviceRow.id).where(DeviceRow.rack_id.in_(rack_ids))).all())
    if device_ids:
        port_ids = list(session.exec(select(DevicePortRow.id).where(DevicePortRow.device_id.in_(device_ids))).all())
        if port_ids:
            cable_ids = [c for c in session.exec(select(ConnectionRow.cable_id).where(or_(
                ConnectionRow.port1_id.in_(port_ids), ConnectionRow.port2_id.in_(port_ids)))).all() if c]
            session.exec(delete(ConnectionRow).where(or_(
                ConnectionRow.port1_id.in_(port_ids), ConnectionRow.port2_id.in_(port_ids))))
            if cable_ids:
                session.exec(delete(CableRow).where(CableRow.id.in_(cable_ids)))
            session.exec(delete(DevicePortRow).where(DevicePortRow.id.in_(port_ids)))
        session.exec(delete(DeviceStatusHistoryRow).where(DeviceStatusHistoryRow.device_id.in_(device_ids)))
        session.exec(delete(DevicePlacementHistoryRow).where(DevicePlacementHistoryRow.device_id.in_(device_ids)))
        session.exec(delete(DeviceRow).where(DeviceRow.id.in_(device_ids)))
    if rack_ids:
        session.exec(delete(DevicePlacementHistoryRow).where(or_(
            DevicePlacementHistoryRow.from_rack_id.in_(rack_ids), DevicePlacementHistoryRow.to_rack_id.in_(rack_ids))))
        session.exec(delete(RackRow).where(RackRow.id.in_(rack_ids)))
    if row_ids:
        session.exec(delete(RackRowRow).where(RackRowRow.id.in_(row_ids)))
    if hall:
        session.delete(hall)
    if site and not site.is_default:
        session.flush()
        if not session.exec(select(HallRow).where(HallRow.site_id == site.id)).first():
            session.delete(site)
    for mfr, model, *_ in DEVICE_TYPES:
        t = _get(session, DeviceTypeRow, manufacturer=mfr, name=model)
        if t and not session.exec(select(DeviceRow.id).where(DeviceRow.device_type_id == t.id)).first():
            from app.modules.images.models import ProfileImageRow
            pids = list(session.exec(select(DeviceTypeProfileRow.id).where(
                DeviceTypeProfileRow.device_type_id == t.id)).all())
            if pids:
                session.exec(delete(ProfileImageRow).where(ProfileImageRow.profile_id.in_(pids)))
            session.exec(delete(DeviceTypeProfileRow).where(DeviceTypeProfileRow.device_type_id == t.id))
            session.delete(t)
    session.flush()


def _fits(session: Session, rack: RackRow, height: int) -> bool:
    """True when every live device in the cabinet stays within `height` U."""
    for d in session.exec(select(DeviceRow).where(DeviceRow.rack_id == rack.id, DeviceRow.deleted_at.is_(None))).all():
        p = session.get(DeviceTypeProfileRow, d.profile_id) if d.profile_id else None
        t = p or (session.get(DeviceTypeRow, d.device_type_id) if d.device_type_id else None)
        if d.position_u + (t.u_height if t else 1) - 1 > height:
            return False
    return True


def seed(session: Session, with_users: bool) -> dict:
    created = {"sites": 0, "halls": 0, "rows": 0, "racks": 0, "device_types": 0, "profiles": 0,
               "devices": 0, "users": 0, "racks_resized": 0, "ports": 0, "connections": 0,
               "profiles_completed": 0, "images": 0, "profiles_published": 0, "devices_linked": 0}
    site = _get(session, SiteRow, name=SITE)
    if site is None:
        site = SiteRow(name=SITE, address="Demo campus, Building 1")
        session.add(site)
        session.flush()
        created["sites"] += 1
    hall = _get(session, HallRow, site_id=site.id, name=HALL)
    if hall is None:
        hall = HallRow(site_id=site.id, name=HALL, aisle_axis="y", odd_side="low")
        session.add(hall)
        session.flush()
        created["halls"] += 1

    racks: dict[str, RackRow] = {}
    for r in range(1, ROWS + 1):
        rname = f"R{r:02d}"
        x, y, orient = row_layout(r)
        row = _get(session, RackRowRow, hall_id=hall.id, name=rname)
        if row is None:
            row = RackRowRow(hall_id=hall.id, name=rname, pos_x=x, pos_y=y, orientation=orient)
            session.add(row)
            session.flush()
            created["rows"] += 1
        for c in range(1, CABINETS + 1):
            cname = f"{rname}-C{c:02d}"
            rack = session.exec(select(RackRow).where(
                RackRow.row_id == row.id, RackRow.name == cname, RackRow.deleted_at.is_(None))).first()
            if rack is None:
                cx, cy, corient = cabinet_layout(r, c)
                rack = RackRow(row_id=row.id, name=cname, u_height=U, pos_x=cx, pos_y=cy, orientation=corient)
                session.add(rack)
                created["racks"] += 1
            elif rack.u_height != U and _fits(session, rack, U):
                rack.u_height = U  # older seeds made 42U demo cabinets: grow them to the standard 53U
                created["racks_resized"] += 1
            racks[cname] = rack
    session.flush()

    types, profiles = _seed_profiles(session, created)

    change_set = new_change_set(session, "script", actor="seed_demo", note="demo seed")
    existing = set(session.exec(select(DeviceRow.host_name).where(DeviceRow.deleted_at.is_(None))).all())
    for cname, devices in PLACED.items():
        rack = racks[cname]
        for host, model, u, status, face in devices:
            if host in existing:
                continue
            lifecycle.create(session, DeviceRow(
                host_name=host, device_type_id=types[model].id, rack_id=rack.id, position_u=u, face=face,
                status=status, serial_number=f"DEMO-{host.upper()}", created_by="seed_demo",
            ), change_set)
            created["devices"] += 1
    for host, model, status in UNPLACED:
        if host in existing:
            continue
        lifecycle.create(session, DeviceRow(
            host_name=host, device_type_id=types[model].id, status=status,
            serial_number=f"DEMO-{host.upper()}", created_by="seed_demo",
        ), change_set)
        created["devices"] += 1

    session.flush()
    _link_demo_devices(session, profiles, created)
    _seed_connections(session, created)

    if with_users:
        for email, role, name, password in DEMO_USERS:
            if _get(session, UserRow, email=email) is None:
                session.add(UserRow(email=email, role=role, display_name=name,
                                    password_hash=hash_password(password), must_change_password=False))
                created["users"] += 1
    session.flush()
    return created


def _seed_profiles(session: Session, created: dict) -> tuple[dict, dict]:
    """Types + their 'Standard' profile, completed, with a DEMO front image, published. Upgrades older demo
    data in place (drafts from p1_17 get the missing fields); a published profile is never edited."""
    from app.modules.device_types.lifecycle import publish
    from app.modules.images.models import ProfileImageRow
    from app.modules.images.router import save_image
    types: dict[str, DeviceTypeRow] = {}
    profiles: dict[str, DeviceTypeProfileRow] = {}
    for mfr, model, u, full, w, h, d, ports in DEVICE_TYPES:
        t = _get(session, DeviceTypeRow, manufacturer=mfr, name=model)
        if t is None:
            t = DeviceTypeRow(manufacturer=mfr, name=model, u_height=u, is_full_depth=full)
            session.add(t)
            session.flush()
            created["device_types"] += 1
        if t.asset_type is None:
            t.asset_type = ASSET_TYPES[model]
        template = {"width_mm": w, "height_mm": h, "depth_mm": d, "is_full_depth": full, "mounting": "rack_19in",
                    "power_type": "DC" if (mfr, model) == ("Juniper", "MX304") else "AC",
                    "weight_kg": WEIGHT_KG[model]}
        profile = _get(session, DeviceTypeProfileRow, device_type_id=t.id, name="Standard")
        if profile is None:
            if not session.exec(select(DeviceTypeProfileRow.id).where(
                    DeviceTypeProfileRow.device_type_id == t.id, DeviceTypeProfileRow.is_default)).first():
                is_default = True
            else:
                is_default = False
            profile = DeviceTypeProfileRow(
                device_type_id=t.id, name="Standard", is_default=is_default, u_height=t.u_height, **template,
                ports=[{"name": f"p{i}", "speed_mbps": 25000 if ports > 8 else 10000}
                       for i in range(1, ports + 1)] or None)
            session.add(profile)
            created["profiles"] += 1
        elif profile.status == "draft":
            missing = {k: v for k, v in template.items() if getattr(profile, k) is None}
            for k, v in missing.items():
                setattr(profile, k, v)
            if missing:
                created["profiles_completed"] += 1
        if t.asset_type == "switch" and profile.orientation is None:  # D58: filling a NULL is allowed even when published
            profile.orientation = "port_front"
            created["orientations"] = created.get("orientations", 0) + 1
        session.flush()
        if not session.exec(select(ProfileImageRow.id).where(
                ProfileImageRow.profile_id == profile.id, ProfileImageRow.face == "front")).first():
            save_image(session, profile, "front", demo_front_image(mfr, model, t.u_height), "image/png",
                       filename=f"demo-{model}.png")
            created["images"] += 1
        if not session.exec(select(ProfileImageRow.id).where(  # rear required to publish (2026-10-24)
                ProfileImageRow.profile_id == profile.id, ProfileImageRow.face == "rear")).first():
            save_image(session, profile, "rear", demo_front_image(mfr, model, t.u_height, "rear"), "image/png",
                       filename=f"demo-{model}-rear.png")
            created["images"] += 1
        if profile.status == "draft":
            publish(session, profile)
            created["profiles_published"] += 1
        types[model], profiles[model] = t, profile
    session.flush()
    return types, profiles


def _link_demo_devices(session: Session, profiles: dict, created: dict) -> None:
    """Every demo device (incl. older seeds' and soft-deleted ones) uses its type's published Standard profile;
    the p1_17 flags on them are cleared. Nothing is deleted."""
    by_type = {p.device_type_id: p for p in profiles.values()}
    for dev in session.exec(select(DeviceRow).where(DeviceRow.host_name.in_(_demo_host_names()))).all():
        prof = by_type.get(dev.device_type_id)
        if prof is None:
            continue
        if dev.profile_id != prof.id and (dev.profile_id is None or session.get(
                DeviceTypeProfileRow, dev.profile_id).status != "published"):
            dev.profile_id = prof.id
            created["devices_linked"] += 1
        if dev.needs_review_reason == "profile_not_published":
            dev.needs_review, dev.needs_review_reason = False, None
    session.flush()


def _seed_connections(session: Session, created: dict) -> None:
    devices = {d.host_name: d for d in session.exec(select(DeviceRow).where(
        DeviceRow.host_name.in_(_demo_host_names()), DeviceRow.deleted_at.is_(None))).all()}

    def port(host, name):
        dev = devices[host]
        p = session.exec(select(DevicePortRow).where(DevicePortRow.device_id == dev.id,
                                                     DevicePortRow.name == name)).first()
        if p is None:
            p = DevicePortRow(device_id=dev.id, name=name,
                              kind="fiber" if name.startswith(("Eth", "et-", "Hu")) else "ethernet")
            session.add(p)
            session.flush()
            created["ports"] += 1
        return p

    for i, (ah, ap, bh, bp, ctype) in enumerate(_demo_links(), start=1):
        if ah not in devices or bh not in devices:
            continue
        pa, pb = port(ah, ap), port(bh, bp)
        if session.exec(select(ConnectionRow.id).where(or_(
                ConnectionRow.port1_id.in_([pa.id, pb.id]), ConnectionRow.port2_id.in_([pa.id, pb.id])))).first():
            continue  # already linked (idempotent)
        cable = CableRow(cable_type=ctype, label=f"DEMO-{i:04d}", color={"RJ45": "blue", "LC": "aqua"}.get(ctype),
                         length_m=3 if ctype == "DAC" else 5)
        session.add(cable)
        session.flush()
        lo, hi = sorted((pa.id, pb.id))
        session.add(ConnectionRow(port1_id=lo, port2_id=hi, cable_id=cable.id))
        created["connections"] += 1
    session.flush()


def run(engine, reseed: bool = False, force: bool = False, users: bool = True) -> dict:
    prod = get_settings().env == "prod"
    if reseed and prod and not force:
        raise SystemExit("Refusing to wipe: DCIM_ENV=prod (pass --force if you really mean it)")
    if users and prod:
        print("DCIM_ENV=prod: skipping the fixed-password demo users", file=sys.stderr)
        users = False
    with Session(engine) as session:
        if reseed:
            wipe(session)
        created = seed(session, users)
        session.commit()
    return created


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--wipe", "--reseed", dest="reseed", action="store_true",
                        help="Delete the demo data first, then seed again")
    parser.add_argument("--force", action="store_true", help="Allow --wipe when DCIM_ENV=prod")
    parser.add_argument("--no-users", action="store_true", help="Do not create the demo logins")
    args = parser.parse_args(argv)
    from app.db import engine

    created = run(engine, reseed=args.reseed, force=args.force, users=not args.no_users)
    print("Created:", ", ".join(f"{k}={v}" for k, v in created.items()))
    print(f"Database: {os.environ.get('DCIM_DATABASE_URL', get_settings().database_url)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
