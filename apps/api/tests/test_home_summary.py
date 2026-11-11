"""GET /home/summary: role split, stale/retired windows, needs-review, unpositioned, parked tiles."""
import re
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, update

from app.modules.device_types.models import DeviceTypeProfileRow
from app.modules.devices.models import DeviceRow
from app.modules.home.constants import (
    HOME_LIST_LIMIT,
    RECENTLY_RETIRED_DAYS,
    STALE_DRAFT_DAYS,
    UNPOSITIONED_DEVICE_LIMIT,
)
from app.timestamps import utcnow
from tests.test_locations import COMPLETE, make_rack, publish_profile

ISO_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")
PARKED_MY_WORK = ("jobs", "dcreqs", "held_imports")
PARKED_ADMIN = ("needs_power_assignment", "port_conflicts", "open_power_mismatches", "workload")


def _assert_parked(tile, key):
    assert tile == {"key": key, "status": "not_available", "message": tile["message"]}
    assert tile["message"]
    assert "count" not in tile and "items" not in tile and "truncated" not in tile
    # No invented numeric data.
    assert not any(isinstance(v, (int, float)) and not isinstance(v, bool) for v in tile.values())


def _set_profile_times(engine, profile_id, **fields):
    with Session(engine) as session:
        session.exec(update(DeviceTypeProfileRow).where(DeviceTypeProfileRow.id == profile_id).values(**fields))
        session.commit()


def _set_device_updated(engine, device_id, when):
    with Session(engine) as session:
        session.exec(update(DeviceRow).where(DeviceRow.id == device_id).values(updated_at=when))
        session.commit()


def _new_type(client, name, asset_type="server"):
    return client.post("/device-types", json={"manufacturer": "Acme", "name": name, "u_height": 2,
                                              "asset_type": asset_type}).json()


def _draft(client, type_id, name):
    return client.post(f"/device-types/{type_id}/profiles", json={"name": name}).json()


def test_summary_requires_auth(anon):
    assert anon.get("/home/summary").status_code == 401


def test_summary_roles_omit_admin_for_non_admins(client_as, client):
    now = utcnow()
    for role in ("technician", "read-only"):
        c = client_as(role)
        r = c.get("/home/summary")
        assert r.status_code == 200, r.text
        body = r.json()
        assert "admin" not in body
        assert set(body) == {"generated_at", "my_work"}
        assert ISO_Z.match(body["generated_at"])
        assert set(body["my_work"]) == set(PARKED_MY_WORK)
        for key in PARKED_MY_WORK:
            _assert_parked(body["my_work"][key], key)

    admin = client.get("/home/summary")
    assert admin.status_code == 200, admin.text
    body = admin.json()
    assert ISO_Z.match(body["generated_at"])
    assert set(body) == {"generated_at", "my_work", "admin"}
    assert "admin" in body and body["admin"] is not None
    assert set(body["my_work"]) == set(PARKED_MY_WORK)
    for key in PARKED_MY_WORK:
        _assert_parked(body["my_work"][key], key)
    admin_sec = body["admin"]
    assert set(admin_sec) == {"profile_health", "device_issues", "workload"}
    assert admin_sec["profile_health"]["key"] == "profile_health"
    assert admin_sec["device_issues"]["key"] == "device_issues"
    _assert_parked(admin_sec["workload"], "workload")
    issues = admin_sec["device_issues"]
    assert set(issues) == {"key", "no_position", "needs_power_assignment", "port_conflicts", "open_power_mismatches"}
    for key in ("needs_power_assignment", "port_conflicts", "open_power_mismatches"):
        _assert_parked(issues[key], key)
    # generated_at is close to now (not a stale clock)
    generated = datetime.fromisoformat(body["generated_at"].replace("Z", "+00:00"))
    assert abs((generated - now).total_seconds()) < 10


def test_stale_draft_boundary_13_14_15_days(client, engine, monkeypatch):
    now = datetime(2026, 11, 11, 14, 0, 0, tzinfo=UTC)
    monkeypatch.setattr("app.modules.home.router.utcnow", lambda: now)
    t = _new_type(client, "StaleBound")
    p13 = _draft(client, t["id"], "d13")
    p14 = _draft(client, t["id"], "d14")
    p15 = _draft(client, t["id"], "d15")
    _set_profile_times(engine, p13["id"], updated_at=now - timedelta(days=STALE_DRAFT_DAYS - 1))
    _set_profile_times(engine, p14["id"], updated_at=now - timedelta(days=STALE_DRAFT_DAYS))
    _set_profile_times(engine, p15["id"], updated_at=now - timedelta(days=STALE_DRAFT_DAYS + 1))

    stale = client.get("/home/summary").json()["admin"]["profile_health"]["stale_drafts"]
    ids = {i["id"] for i in stale["items"]}
    assert p13["id"] not in ids
    assert p14["id"] in ids and p15["id"] in ids
    assert stale["count"] >= 2
    assert stale["filter"] == "status=draft"
    for item in stale["items"]:
        assert set(item) == {"id", "name", "updated_at"}
        assert ISO_Z.match(item["updated_at"])
        assert "Acme" in item["name"] and "StaleBound" in item["name"]


def test_needs_review_uses_usability_rule(client, engine):
    server = _new_type(client, "Srv", "server")
    switch = _new_type(client, "Sw", "switch")
    # Published server missing a rear image -> rear_image_missing (usability()).
    rear = _draft(client, server["id"], "NoRear")
    publish_profile(client, server["id"], rear["id"], fields=COMPLETE)
    with Session(engine) as session:
        from sqlmodel import delete
        from app.modules.images.models import ProfileImageRow
        session.exec(delete(ProfileImageRow).where(ProfileImageRow.profile_id == rear["id"],
                                                   ProfileImageRow.face == "rear"))
        session.commit()
    # Published switch missing orientation -> orientation_missing.
    ori = _draft(client, switch["id"], "NoOri")
    publish_profile(client, switch["id"], ori["id"], fields={**COMPLETE, "orientation": "port_front"})
    client.patch(f"/device-types/{switch['id']}/profiles/{ori['id']}", json={"orientation": None})
    # After publish, orientation is frozen? Might 409. If so, drop it in the DB.
    got = client.get(f"/device-types/{switch['id']}/profiles/{ori['id']}").json()
    if got.get("orientation"):
        _set_profile_times(engine, ori["id"], orientation=None)
        got = client.get(f"/device-types/{switch['id']}/profiles/{ori['id']}").json()
    assert "orientation_missing" in got["usable_issues"]
    # A complete published profile is not needs-review.
    ok = _draft(client, server["id"], "Ready")
    publish_profile(client, server["id"], ok["id"], fields=COMPLETE)
    # A draft is not needs-review (that's stale drafts / by_status).
    _draft(client, server["id"], "StillDraft")

    health = client.get("/home/summary").json()["admin"]["profile_health"]
    review = health["needs_review"]
    ids = {i["id"] for i in review["items"]}
    assert rear["id"] in ids and ori["id"] in ids
    assert ok["id"] not in ids
    assert review["count"] >= 2
    assert review["filter"] == "status=published&usable=false"
    assert review["by_issue"]["rear_image_missing"] >= 1
    assert review["by_issue"]["orientation_missing"] >= 1
    by_id = {i["id"]: i for i in review["items"]}
    assert by_id[rear["id"]]["usable_issue"] == "rear_image_missing"
    assert "rear_image_missing" in by_id[rear["id"]]["usable_issues"]
    assert set(by_id[rear["id"]]) == {"id", "name", "usable_issue", "usable_issues"}
    # Matches GET /profiles?usable=false for the same ids (same usability() rule).
    unusable = {p["id"]: p for p in client.get("/profiles", params={"usable": "false", "status": "published"}).json()}
    assert rear["id"] in unusable and ori["id"] in unusable and ok["id"] not in unusable
    assert unusable[rear["id"]]["usable_issues"] == by_id[rear["id"]]["usable_issues"]


def test_recently_retired_30_day_window(client, engine, monkeypatch):
    now = datetime(2026, 11, 11, 14, 0, 0, tzinfo=UTC)
    monkeypatch.setattr("app.modules.home.router.utcnow", lambda: now)
    t = _new_type(client, "RetireWin")
    inside = _draft(client, t["id"], "InWin")
    edge = _draft(client, t["id"], "Edge")
    outside = _draft(client, t["id"], "OutWin")
    for p in (inside, edge, outside):
        publish_profile(client, t["id"], p["id"], fields=COMPLETE)
        assert client.post(f"/profiles/{p['id']}/retire").status_code == 200
    _set_profile_times(engine, inside["id"], retired_at=now - timedelta(days=RECENTLY_RETIRED_DAYS - 1))
    _set_profile_times(engine, edge["id"], retired_at=now - timedelta(days=RECENTLY_RETIRED_DAYS))
    _set_profile_times(engine, outside["id"], retired_at=now - timedelta(days=RECENTLY_RETIRED_DAYS + 1))

    recent = client.get("/home/summary").json()["admin"]["profile_health"]["recently_retired"]
    ids = {i["id"] for i in recent["items"]}
    assert inside["id"] in ids and edge["id"] in ids
    assert outside["id"] not in ids
    assert recent["filter"] == "status=retired"
    for item in recent["items"]:
        assert set(item) == {"id", "name", "retired_at"}
        assert ISO_Z.match(item["retired_at"])


def test_profile_health_counts_recently_changed_and_truncation(client, engine):
    t = _new_type(client, "Counts")
    ids = []
    for i in range(HOME_LIST_LIMIT + 2):
        ids.append(_draft(client, t["id"], f"P{i}")["id"])
    health = client.get("/home/summary").json()["admin"]["profile_health"]
    assert health["by_status"]["draft"] >= HOME_LIST_LIMIT + 2
    assert set(health["by_status"]) == {"draft", "published", "retired"}
    changed = health["recently_changed"]
    assert changed["count"] >= HOME_LIST_LIMIT + 2
    assert changed["truncated"] is True
    assert len(changed["items"]) == HOME_LIST_LIMIT
    for item in changed["items"]:
        assert set(item) == {"id", "name", "status", "updated_at", "published_at", "retired_at"}
        assert ISO_Z.match(item["updated_at"])
        if item["published_at"] is not None:
            assert ISO_Z.match(item["published_at"])
        if item["retired_at"] is not None:
            assert ISO_Z.match(item["retired_at"])
        if item["status"] == "draft":
            assert item["published_at"] is None and item["retired_at"] is None


def test_unpositioned_devices_install_active_only(client, engine):
    t = _new_type(client, "Devs")
    p = _draft(client, t["id"], "Std")
    publish_profile(client, t["id"], p["id"], fields=COMPLETE)
    rack = make_rack(client)
    placed = client.post("/devices", json={"host_name": "placed-1", "profile_id": p["id"],
                                           "rack_id": rack["id"], "position_u": 1, "status": "install"}).json()
    inst = client.post("/devices", json={"host_name": "open-install", "profile_id": p["id"],
                                         "status": "install"}).json()
    act = client.post("/devices", json={"host_name": "open-active", "profile_id": p["id"],
                                        "status": "active"}).json()
    decom = client.post("/devices", json={"host_name": "decom-free", "profile_id": p["id"],
                                          "status": "decom"}).json()
    assert inst["rack_id"] is None and act["rack_id"] is None and decom["rack_id"] is None

    tile = client.get("/home/summary").json()["admin"]["device_issues"]["no_position"]
    ids = {i["id"] for i in tile["items"]}
    assert inst["id"] in ids and act["id"] in ids
    assert placed["id"] not in ids and decom["id"] not in ids
    assert tile["count"] >= 2
    assert tile["filter"] == "status=install&status=active&unplaced=true"
    assert tile["truncated"] is (tile["count"] > UNPOSITIONED_DEVICE_LIMIT)
    by_id = {i["id"]: i for i in tile["items"]}
    assert by_id[inst["id"]]["hostname"] == "open-install"
    assert by_id[inst["id"]]["status"] == "install"
    assert "host_name" not in by_id[inst["id"]]
    for item in tile["items"]:
        assert set(item) == {"id", "hostname", "status", "updated_at"}
        assert ISO_Z.match(item["updated_at"])


def test_unpositioned_list_is_capped(client, engine):
    t = _new_type(client, "Cap")
    p = _draft(client, t["id"], "Std")
    publish_profile(client, t["id"], p["id"], fields=COMPLETE)
    for i in range(UNPOSITIONED_DEVICE_LIMIT + 3):
        r = client.post("/devices", json={"host_name": f"loose-{i}", "profile_id": p["id"],
                                          "status": "install"})
        assert r.status_code == 201, r.text
    tile = client.get("/home/summary").json()["admin"]["device_issues"]["no_position"]
    assert tile["count"] >= UNPOSITIONED_DEVICE_LIMIT + 3
    assert tile["truncated"] is True
    assert len(tile["items"]) == UNPOSITIONED_DEVICE_LIMIT
