"""Device-type profile timestamps are UTC with a trailing Z."""
import re
from datetime import datetime

from sqlmodel import Session, update

from app.modules.device_types.models import DeviceTypeProfileRow
from tests.test_locations import COMPLETE, publish_profile

ISO_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


def test_profiles_list_timestamps_utc_z(client, engine):
    t = client.post("/device-types", json={"manufacturer": "Acme", "name": "X100", "u_height": 2,
                                           "asset_type": "server"}).json()
    draft = client.post(f"/device-types/{t['id']}/profiles", json={"name": "Draft"}).json()
    published = client.post(f"/device-types/{t['id']}/profiles", json={"name": "Live"}).json()
    publish_profile(client, t["id"], published["id"], fields=COMPLETE)
    retired = client.post(f"/device-types/{t['id']}/profiles", json={"name": "Old"}).json()
    publish_profile(client, t["id"], retired["id"], fields=COMPLETE)
    assert client.post(f"/profiles/{retired['id']}/retire").status_code == 200

    # A naive UTC value stored as in older SQLite rows must still come back with Z.
    stamp = datetime(2026, 11, 4, 1, 12, 31, 331192)
    with Session(engine) as session:
        session.exec(update(DeviceTypeProfileRow).where(DeviceTypeProfileRow.id == draft["id"])
                     .values(updated_at=stamp))
        session.commit()

    items = {p["id"]: p for p in client.get("/profiles").json() if p["id"] in {draft["id"], published["id"], retired["id"]}}
    d, p, r = items[draft["id"]], items[published["id"]], items[retired["id"]]

    assert d["published_at"] is None and d["retired_at"] is None
    assert ISO_Z.match(d["updated_at"]) and d["updated_at"] == "2026-11-04T01:12:31.331192Z"

    assert ISO_Z.match(p["published_at"]) and p["retired_at"] is None and ISO_Z.match(p["updated_at"])
    assert p["status"] == "published"

    assert ISO_Z.match(r["published_at"]) and ISO_Z.match(r["retired_at"]) and ISO_Z.match(r["updated_at"])
    assert r["status"] == "retired"
    # Existing fields are still present.
    for item in (d, p, r):
        assert item["name"] and "usable" in item and "device_count" in item


DT_KEYS = ("created_at", "updated_at", "published_at", "retired_at")


def _assert_z(body, *, published=False, retired=False, updated=None):
    for key in DT_KEYS:
        assert key in body
        value = body[key]
        if value is not None:
            assert ISO_Z.match(value), (key, value)
    assert body["created_at"] and body["updated_at"]
    if updated is not None:
        assert body["updated_at"] == updated
    if published:
        assert body["published_at"]
    else:
        assert body["published_at"] is None
    if retired:
        assert body["retired_at"]
    else:
        assert body["retired_at"] is None


def test_device_type_profile_reads_use_utc_z(client, engine):
    t = client.post("/device-types", json={"manufacturer": "Acme", "name": "Y200", "u_height": 2,
                                           "asset_type": "server"}).json()
    draft = client.post(f"/device-types/{t['id']}/profiles", json={"name": "Draft"}).json()
    published = client.post(f"/device-types/{t['id']}/profiles", json={"name": "Live"}).json()
    publish_profile(client, t["id"], published["id"], fields=COMPLETE)
    retired = client.post(f"/device-types/{t['id']}/profiles", json={"name": "Old"}).json()
    publish_profile(client, t["id"], retired["id"], fields=COMPLETE)
    assert client.post(f"/profiles/{retired['id']}/retire").status_code == 200

    stamp = datetime(2026, 11, 4, 1, 12, 31, 331192)
    with Session(engine) as session:
        session.exec(update(DeviceTypeProfileRow).where(DeviceTypeProfileRow.id == draft["id"])
                     .values(updated_at=stamp))
        session.commit()

    listed = {p["id"]: p for p in client.get(f"/device-types/{t['id']}/profiles").json()}
    d, p, r = listed[draft["id"]], listed[published["id"]], listed[retired["id"]]
    _assert_z(d, updated="2026-11-04T01:12:31.331192Z")
    _assert_z(p, published=True)
    _assert_z(r, published=True, retired=True)

    got = client.get(f"/device-types/{t['id']}/profiles/{draft['id']}").json()
    _assert_z(got, updated="2026-11-04T01:12:31.331192Z")
    pub = client.get(f"/device-types/{t['id']}/profiles/{published['id']}").json()
    _assert_z(pub, published=True)
    ret = client.get(f"/device-types/{t['id']}/profiles/{retired['id']}").json()
    _assert_z(ret, published=True, retired=True)


def test_device_type_profile_writes_share_schema_and_utc_z(client):
    t = client.post("/device-types", json={"manufacturer": "Acme", "name": "Y201", "u_height": 2,
                                           "asset_type": "server"}).json()
    created = client.post(f"/device-types/{t['id']}/profiles", json={"name": "Std"}).json()
    _assert_z(created)
    patched = client.patch(f"/device-types/{t['id']}/profiles/{created['id']}", json={"name": "Std v2"}).json()
    _assert_z(patched)
    published = publish_profile(client, t["id"], created["id"], fields=COMPLETE)
    _assert_z(published, published=True)
    # Flat publish alias returns the same DeviceProfile schema.
    again = client.post(f"/profiles/{created['id']}/publish").json()
    _assert_z(again, published=True)
    cloned = client.post(f"/profiles/{created['id']}/clone", json={}).json()
    _assert_z(cloned)
    assert cloned["id"] != created["id"] and cloned["status"] == "draft"
    retired = client.post(f"/profiles/{created['id']}/retire").json()
    _assert_z(retired, published=True, retired=True)
