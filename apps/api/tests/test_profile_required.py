"""Preston: a profile is mandatory for every placement (reverses p1_08 typeless placement)."""
from tests.test_lifecycle import dtype, make_rack

CODE = "profile_required"


RAW = {"X-Test-Raw": "1"}  # bypass the conftest generic-profile shim
CSV = {"Content-Type": "text/csv", **RAW}


def test_d36_every_new_device_needs_a_published_profile(client):
    rack = make_rack(client)
    r = client.post("/devices", json={"host_name": "mystery", "rack_id": rack["id"], "position_u": 5}, headers=RAW)
    assert r.status_code == 422 and r.json()["detail"]["code"] == CODE
    # D36: unplaced too
    r = client.post("/devices", json={"host_name": "spare"}, headers=RAW)
    assert r.status_code == 422 and r.json()["detail"]["code"] == CODE


def test_type_resolves_to_default_profile_and_fit_uses_it(client):
    rack = make_rack(client)
    t2 = dtype(client, 2)
    d = client.post("/devices", json={"host_name": "a", "rack_id": rack["id"], "position_u": 5,
                                      "device_type_id": t2["id"]})
    assert d.status_code == 201 and d.json()["profile_id"] is not None
    # U6 is taken by the 2U device on both faces (full depth)
    r = client.post("/devices", json={"host_name": "b", "rack_id": rack["id"], "position_u": 6, "face": "rear",
                                      "device_type_id": dtype(client, 1)["id"]})
    assert r.status_code == 409


def test_csv_import_requires_profile_structured_errors(client):
    rack = make_rack(client)
    raw = client.post("/device-types", json={"manufacturer": "Acme", "name": "bare", "u_height": 1}).json()
    draft = client.get(f"/device-types/{raw['id']}/profiles").json()[0]
    ok = dtype(client, 1, name="ok1")
    body = (f"host_name,rack_id,position_u,device_type_id\nx1,{rack['id']},3,\nx2,,,{raw['id']}\n"
            f"x3,{rack['id']},7,{ok['id']}\n")
    r = client.post("/devices/import?dry_run=false", content=body, headers=CSV).json()
    assert r["created"] == 0 and [e["row"] for e in r["errors"]] == [2, 3]  # all-or-nothing
    assert r["errors"][0]["details"][0]["code"] == CODE
    d = r["errors"][1]["details"][0]
    assert d["code"] == "profile_not_published" and d["profile_id"] == draft["id"] and d["profile_status"] == "draft"
    assert client.get("/devices").json() == []


def test_draft_profile_cannot_be_used_and_readiness(client):
    rack = make_rack(client)
    raw = client.post("/device-types", json={"manufacturer": "Acme", "name": "bare", "u_height": 1}).json()
    prof = client.get(f"/device-types/{raw['id']}/profiles").json()[0]
    assert prof["status"] == "draft" and {k: prof["readiness"][k] for k in ("ready", "missing")} == {"ready": False, "missing": [
        "asset_type", "width_mm", "height_mm", "depth_mm", "mounting", "power_type", "front_image", "rear_image"]}
    for body in ({"host_name": "a", "rack_id": rack["id"], "position_u": 1, "device_type_id": raw["id"]},
                 {"host_name": "b", "device_type_id": raw["id"]}, {"host_name": "c", "profile_id": prof["id"]}):
        r = client.post("/devices", json=body)
        assert r.status_code == 422 and r.json()["detail"]["code"] == "profile_not_published", body
    base = f"/device-types/{raw['id']}/profiles/{prof['id']}"
    r = client.post(f"{base}/publish")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "profile_not_ready"
    assert "front_image" in r.json()["detail"]["missing"]
    from tests.test_locations import publish_profile
    pub = publish_profile(client, raw["id"], prof["id"])
    assert pub["status"] == "published" and pub["published_at"] and pub["readiness"]["ready"]
    assert client.post(f"/profiles/{prof['id']}/publish").status_code == 200  # flat path, idempotent
    r = client.patch(base, json={"depth_mm": 900})
    assert r.status_code == 409 and r.json()["detail"]["fields"] == ["depth_mm"]
    assert client.patch(base, json={"color_hex": "#112233"}).status_code == 200  # cosmetic edits ok
    assert client.post("/devices", json={"host_name": "b", "device_type_id": raw["id"]}).status_code == 201
    assert next(p for p in client.get("/profiles").json() if p["id"] == prof["id"])["status"] == "published"
    assert client.patch(base, json={"weight_kg": 0}).status_code == 422


def test_publish_requires_admin(client, client_as):
    raw = client.post("/device-types", json={"manufacturer": "Acme", "name": "bare", "u_height": 1}).json()
    prof = client.get(f"/device-types/{raw['id']}/profiles").json()[0]
    assert client_as("technician").post(f"/device-types/{raw['id']}/profiles/{prof['id']}/publish").status_code == 403


def test_position_still_requires_rack(client):
    assert client.post("/devices", json={"host_name": "x", "position_u": 3}).status_code == 422


# ---- item 49: needs_review flags (set by migrations/scripts; read-only in the API) ----
import pytest  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from app.modules.devices.models import DeviceRow  # noqa: E402


def _flagged(engine, rack, reason, **kw):
    with Session(engine) as s:
        d = DeviceRow(host_name=f"old-{reason}", rack_id=rack["id"], position_u=5, status="active",
                      needs_review=True, needs_review_reason=reason, **kw)
        s.add(d)
        s.commit()
        return d.id


def test_needs_review_check_pair(engine):
    with Session(engine) as s:
        s.add(DeviceRow(host_name="x", needs_review=True))
        with pytest.raises(IntegrityError):
            s.flush()
        s.rollback()
        s.add(DeviceRow(host_name="y", needs_review_reason="other"))
        with pytest.raises(IntegrityError):
            s.flush()
        s.rollback()
        s.add(DeviceRow(host_name="z", needs_review=True, needs_review_reason="bogus"))
        with pytest.raises(IntegrityError):
            s.flush()


@pytest.mark.pre_p1_18
def test_placed_without_profile_flagged_locked_and_fixable(client, engine):
    rack = make_rack(client)
    dev = _flagged(engine, rack, "placed_without_profile")
    assert [d["id"] for d in client.get("/devices?needs_review=true").json()] == [dev]
    assert client.get("/devices?needs_review=false").json() == []
    el = client.get(f"/racks/{rack['id']}/elevation").json()["devices"][0]
    assert el["needs_review_reason"] == "placed_without_profile" and el["device_type"] is None
    t1 = dtype(client, 1)
    # still blocks 1U on both faces until removed
    assert client.post("/devices", json={"host_name": "n", "rack_id": rack["id"], "position_u": 5, "face": "rear",
                                         "device_type_id": t1["id"]}).status_code == 409
    r = client.patch(f"/devices/{dev}", json={"host_name": "renamed"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "placed_without_profile"
    assert client.patch(f"/devices/{dev}", json={"position_u": 9}).status_code == 409
    # read-only: not accepted in PATCH
    assert client.patch(f"/devices/{dev}", json={"needs_review": False}).status_code == 422
    prof = next(p for p in client.get(f"/device-types/{t1['id']}/profiles").json() if p["is_default"])
    r = client.patch(f"/devices/{dev}", json={"profile_id": prof["id"]})
    assert r.status_code == 200 and r.json()["needs_review"] is False and r.json()["device_type_id"] == t1["id"]


def test_profile_not_published_flag_kept_until_publish(client, engine):
    rack = make_rack(client)
    raw = client.post("/device-types", json={"manufacturer": "Acme", "name": "bare", "u_height": 1}).json()
    draft = client.get(f"/device-types/{raw['id']}/profiles").json()[0]
    dev = _flagged(engine, rack, "profile_not_published", device_type_id=raw["id"], profile_id=draft["id"])
    assert client.patch(f"/devices/{dev}", json={"notes": "x"}).status_code == 409
    r = client.patch(f"/devices/{dev}", json={"rack_id": None, "position_u": None})
    assert r.status_code == 200, r.text
    assert r.json()["needs_review"] is True and r.json()["profile_id"] == draft["id"]  # unplace keeps profile_id
    from tests.test_locations import publish_profile
    publish_profile(client, raw["id"], draft["id"])
    assert client.get(f"/devices/{dev}").json()["needs_review"] is False  # publishing clears the flag


def test_needs_review_read_only_in_csv(client):
    body = "host_name,needs_review,needs_review_reason\nq1,true,other\n"
    r = client.post("/devices/import?dry_run=false", content=body, headers={"Content-Type": "text/csv"})
    assert r.status_code == 200 and r.json()["created"] == 1
    d = client.get("/devices?q=q1").json()[0]
    assert d["needs_review"] is False and d["needs_review_reason"] is None
