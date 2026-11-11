"""GET /profiles exposes published_at, retired_at and updated_at as UTC with a trailing Z."""
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
