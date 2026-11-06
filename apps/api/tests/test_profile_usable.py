"""Computed `usable` flag: published + complete readiness (rear image rule added later). One error code."""
from sqlmodel import Session, delete

from app.modules.images.models import ProfileImageRow
from tests.test_locations import COMPLETE, make_rack, publish_profile, tiny_png


def _published_without_rear(client, engine, name="Legacy"):
    t = client.post("/device-types", json={"manufacturer": "Old", "name": name, "u_height": 1,
                                           "asset_type": "server"}).json()
    p = client.post(f"/device-types/{t['id']}/profiles", json={"name": f"{name}-p"}).json()
    publish_profile(client, t["id"], p["id"], fields=COMPLETE)
    return t, p


def _drop_rear(engine, pid):  # simulates a profile published before the rear-image rule
    with Session(engine) as s:
        s.exec(delete(ProfileImageRow).where(ProfileImageRow.profile_id == pid, ProfileImageRow.face == "rear"))
        s.commit()


def test_usable_flag_and_refusals(client, engine):
    t, p = _published_without_rear(client, engine)
    rack = make_rack(client)
    keep = client.post("/devices", json={"host_name": "old-1", "profile_id": p["id"], "rack_id": rack["id"],
                                         "position_u": 1})
    assert keep.status_code == 201, keep.text
    _drop_rear(engine, p["id"])
    base = f"/device-types/{t['id']}/profiles/{p['id']}"
    prof = client.get(base).json()
    assert prof["status"] == "published" and prof["usable"] is False and prof["usable_issue"] == "rear_image_missing"
    assert prof["usable_issues"] == ["rear_image_missing"] and prof["readiness"]["flags"] == ["rear_image_missing"]
    assert p["id"] in [x["id"] for x in client.get(f"/device-types/{t['id']}/profiles", params={"usable": "false"}).json()]
    assert p["id"] not in [x["id"] for x in client.get(f"/device-types/{t['id']}/profiles", params={"usable": "true"}).json()]
    item = next(i for i in client.get("/profiles").json() if i["id"] == p["id"])
    assert item["usable"] is False and item["usable_issue"] == "rear_image_missing"
    assert p["id"] not in [i["id"] for i in client.get("/profiles", params={"usable": "true"}).json()]
    assert p["id"] in [i["id"] for i in client.get("/profiles", params={"usable": "false"}).json()]

    def refused(r):
        assert r.status_code == 422, r.text
        d = r.json()["detail"]
        assert d["code"] == "profile_not_usable" and d["issues"] == ["rear_image_missing"] and d["profile_id"] == p["id"]
        assert d["message"] and d["reason"] == "rear_image_missing"
    refused(client.post("/devices", json={"host_name": "new-1", "profile_id": p["id"]}))
    refused(client.post(f"/racks/{rack['id']}/devices", json={"host_name": "new-2", "profile_id": p["id"],
                                                               "position_u": 5}))
    # profile switch onto it
    other_t, other_p = _published_without_rear(client, engine, "Other")
    mover = client.post("/devices", json={"host_name": "mv", "profile_id": other_p["id"]}).json()
    refused(client.patch(f"/devices/{mover['id']}", json={"profile_id": p["id"]}))
    # device_type_id resolving to the unusable default profile -> same error
    client.patch(f"/device-types/{t['id']}/profiles/{p['id']}", json={"is_default": True})
    assert client.get(f"/device-types/{t['id']}/profiles/{p['id']}").json()["is_default"]
    refused(client.post("/devices", json={"host_name": "by-type", "device_type_id": t["id"]}))
    refused(client.post(f"/profiles/{p['id']}/adopt", json={"device_ids": [mover["id"]]}))
    # CSV row error
    r = client.post("/devices/import?dry_run=true", content=f"host_name,profile_id\ncsv-1,{p['id']}\n",
                    headers={"content-type": "text/csv"})
    body = r.json()
    errs = body.get("errors") or body.get("detail", {}).get("errors")
    assert errs and errs[0]["details"][0]["code"] == "profile_not_usable", body
    # existing device untouched: still placed, not flagged, non-switching PATCH works, can move U
    d = client.get(f"/devices/{keep.json()['id']}").json()
    assert d["rack_id"] == rack["id"] and not d["needs_review"]
    assert client.patch(f"/devices/{d['id']}", json={"notes": "still fine"}).status_code == 200
    assert client.patch(f"/devices/{d['id']}", json={"position_u": 3}).status_code == 200
    # adding a rear image makes it usable again
    assert client.put(f"{base}/images/rear", content=tiny_png(), headers={"content-type": "image/png"}).status_code == 201
    assert client.get(base).json()["usable"] is True
    assert client.post("/devices", json={"host_name": "new-1", "profile_id": p["id"]}).status_code == 201
    assert p["id"] in [i["id"] for i in client.get("/profiles", params={"usable": "true"}).json()]


def test_draft_usable_issue(client):
    t = client.post("/device-types", json={"manufacturer": "X", "name": "D", "u_height": 1}).json()
    p = client.post(f"/device-types/{t['id']}/profiles", json={"name": "d"}).json()
    assert p["usable"] is False and p["usable_issue"] == "profile_draft"
    assert p["usable_issues"][0] == "profile_draft" and "rear_image_missing" in p["usable_issues"]


def test_usable_filter_and_python_rule_agree(client, engine):
    """One rule: ?usable= on both list endpoints == usability() == the device-create refusal."""
    from app.modules.device_types.lifecycle import readiness_map, usability
    from app.modules.device_types.models import DeviceTypeProfileRow
    cases = {}
    t = client.post("/device-types", json={"manufacturer": "Agree", "name": "Srv", "u_height": 1,
                                           "asset_type": "server"}).json()
    cases["draft"] = client.post(f"/device-types/{t['id']}/profiles", json={"name": "draft"}).json()["id"]
    ready = client.post(f"/device-types/{t['id']}/profiles", json={"name": "ready"}).json()
    publish_profile(client, t["id"], ready["id"], fields=COMPLETE)
    cases["ready"] = ready["id"]
    ret = client.post(f"/device-types/{t['id']}/profiles", json={"name": "ret"}).json()
    publish_profile(client, t["id"], ret["id"], fields=COMPLETE)
    assert client.post(f"/profiles/{ret['id']}/retire").status_code == 200
    cases["retired"] = ret["id"]
    norear = client.post(f"/device-types/{t['id']}/profiles", json={"name": "norear"}).json()
    publish_profile(client, t["id"], norear["id"], fields=COMPLETE)
    _drop_rear(engine, norear["id"])
    cases["no_rear"] = norear["id"]
    sw = client.post(f"/device-types/{t['id']}/profiles", json={"name": "sw"}).json()
    publish_profile(client, t["id"], sw["id"], fields=COMPLETE)
    # type later becomes a switch: published, no orientation; also drop its rear -> both issues, rear first
    assert client.patch(f"/device-types/{t['id']}", json={"asset_type": "switch"}).status_code == 200
    cases["switch_no_orientation"] = sw["id"]
    expected = {"draft": False, "ready": False, "retired": False, "no_rear": False, "switch_no_orientation": False}
    # after the switch change every profile on t lacks orientation; give 'ready' one so it stays ready
    assert client.patch(f"/device-types/{t['id']}/profiles/{ready['id']}",
                        json={"orientation": "port_front"}).status_code == 200
    expected["ready"] = True
    flat_true = {i["id"] for i in client.get("/profiles", params={"usable": "true", "limit": 500}).json()}
    flat_false = {i["id"] for i in client.get("/profiles", params={"usable": "false", "limit": 500}).json()}
    typ_true = {i["id"] for i in client.get(f"/device-types/{t['id']}/profiles", params={"usable": "true"}).json()}
    typ_false = {i["id"] for i in client.get(f"/device-types/{t['id']}/profiles", params={"usable": "false"}).json()}
    with Session(engine) as s:
        rows = [s.get(DeviceTypeProfileRow, pid) for pid in cases.values()]
        rm = readiness_map(s, rows)
        py = {r.id: usability(r.status, rm[r.id]) for r in rows}
    for name, pid in cases.items():
        u = expected[name]
        assert py[pid][0] is u, (name, py[pid])
        assert (pid in flat_true) is u and (pid in flat_false) is (not u), name
        assert (pid in typ_true) is u and (pid in typ_false) is (not u), name
        r = client.post("/devices", json={"host_name": f"agree-{name}", "profile_id": pid})
        assert (r.status_code == 201) is u, (name, r.text)
        if not u and r.json()["detail"]["code"] == "profile_not_usable":
            d = r.json()["detail"]
            assert d["issues"] == py[pid][1] and d["reason"] == py[pid][1][0]
    assert py[cases["draft"]][1][0] == "profile_draft" and py[cases["retired"]][1][0] == "profile_retired"
    assert py[cases["no_rear"]][1] == ["rear_image_missing", "orientation_missing"]
    assert py[cases["switch_no_orientation"]][1] == ["orientation_missing"]


def test_issue_priority_order():
    from app.modules.device_types.lifecycle import usability
    ok, issues = usability("draft", {"missing": ["width_mm", "front_image", "rear_image", "orientation"]})
    assert not ok and issues == ["profile_draft", "rear_image_missing", "orientation_missing", "width_mm_missing",
                                 "front_image_missing"]
