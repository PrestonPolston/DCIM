"""GET /home/search: roles, short q, limits, LIKE escaping, related names."""
import re

from app.modules.home.constants import SEARCH_DEFAULT_LIMIT, SEARCH_MAX_LIMIT, SEARCH_MIN_CHARS

ISO_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")
DEVICE_KEYS = {"id", "label", "hostname", "serial", "status", "rack_id", "rack_name", "position_u"}
CABINET_KEYS = {"id", "label", "name", "row_id", "row_name", "hall_id", "hall_name"}
ROW_KEYS = {"id", "label", "name", "hall_id", "hall_name", "site_id", "site_name"}
HALL_KEYS = {"id", "label", "name", "site_id", "site_name"}
GROUP_ORDER = ("devices", "cabinets", "rows", "halls")


def _assert_parked(tile, key):
    assert tile == {"key": key, "status": "not_available", "message": tile["message"]}
    assert tile["message"]
    assert "count" not in tile and "items" not in tile and "truncated" not in tile
    assert not any(isinstance(v, (int, float)) and not isinstance(v, bool) for v in tile.values())


def _assert_envelope(body, query):
    assert set(body) == {"query", "generated_at", "groups", "parked"}
    assert body["query"] == query
    assert ISO_Z.match(body["generated_at"])
    assert [g["key"] for g in body["groups"]] == list(GROUP_ORDER)
    for group in body["groups"]:
        assert set(group) == {"key", "count", "truncated", "items"}
        assert group["count"] >= len(group["items"])
        assert group["truncated"] is (group["count"] > len(group["items"]))
    assert len(body["parked"]) == 1
    _assert_parked(body["parked"][0], "dcreqs")


def _group(body, key):
    return next(g for g in body["groups"] if g["key"] == key)


def _layout(client, site, hall="Hall Alpha", row="Row Sigma", rack="C03"):
    site_row = client.post("/sites", json={"name": site}).json()
    hall_row = client.post("/halls", json={"site_id": site_row["id"], "name": hall}).json()
    row_row = client.post("/rows", json={"hall_id": hall_row["id"], "name": row}).json()
    rack_row = client.post("/racks", json={"row_id": row_row["id"], "name": rack, "u_height": 42}).json()
    return site_row, hall_row, row_row, rack_row


def test_search_requires_auth(anon):
    assert anon.get("/home/search", params={"q": "ab"}).status_code == 401


def test_search_short_q_is_422(client):
    for q in ("", "a", " ", "  ", " b"):
        r = client.get("/home/search", params={"q": q})
        assert r.status_code == 422, (q, r.text)
    assert client.get("/home/search").status_code == 422


def test_search_all_signed_in_roles_and_no_admin_fields(client_as, client):
    site, hall, row, rack = _layout(client, site="RoleSite")
    device = client.post("/devices", json={
        "host_name": "r01c03-srv-09",
        "serial_number": "SN123ROLE",
        "status": "install",
        "rack_id": rack["id"],
        "position_u": 20,
    }).json()
    assert device["id"]

    for role in ("admin", "technician", "read-only"):
        c = client if role == "admin" else client_as(role)
        r = c.get("/home/search", params={"q": "r01c"})
        assert r.status_code == 200, (role, r.text)
        body = r.json()
        _assert_envelope(body, "r01c")
        devices = _group(body, "devices")
        hit = next(i for i in devices["items"] if i["id"] == device["id"])
        assert set(hit) == DEVICE_KEYS
        assert hit == {
            "id": device["id"],
            "label": "r01c03-srv-09",
            "hostname": "r01c03-srv-09",
            "serial": "SN123ROLE",
            "status": "install",
            "rack_id": rack["id"],
            "rack_name": "C03",
            "position_u": 20,
        }
        assert "host_name" not in hit and "serial_number" not in hit


def test_search_matches_name_and_serial_case_insensitive(client):
    site, hall, row, rack = _layout(client, site="MatchSite", hall="Hall Zulu",
                                    row="Row Zulu", rack="R99")
    by_host = client.post("/devices", json={
        "host_name": "Srv-Alpha", "serial_number": "AA111", "status": "active",
        "rack_id": rack["id"], "position_u": 4,
    }).json()
    by_serial = client.post("/devices", json={
        "host_name": "other-host", "serial_number": "SN-xyz-77", "status": "install",
    }).json()

    body = client.get("/home/search", params={"q": "srv-a"}).json()
    _assert_envelope(body, "srv-a")
    host_ids = {i["id"] for i in _group(body, "devices")["items"]}
    assert by_host["id"] in host_ids
    assert by_serial["id"] not in host_ids
    hit = next(i for i in _group(body, "devices")["items"] if i["id"] == by_host["id"])
    assert hit["hostname"] == "Srv-Alpha" and hit["rack_name"] == "R99" and hit["position_u"] == 4

    serial_body = client.get("/home/search", params={"q": "sn-x"}).json()
    serial_ids = {i["id"] for i in _group(serial_body, "devices")["items"]}
    assert by_serial["id"] in serial_ids
    assert by_host["id"] not in serial_ids
    serial_hit = next(i for i in _group(serial_body, "devices")["items"] if i["id"] == by_serial["id"])
    assert serial_hit["serial"] == "SN-xyz-77"
    assert serial_hit["rack_id"] is None and serial_hit["rack_name"] is None
    assert serial_hit["position_u"] is None

    places = client.get("/home/search", params={"q": "ZULU"}).json()
    halls = _group(places, "halls")
    rows = _group(places, "rows")
    assert any(i["id"] == hall["id"] and i["name"] == "Hall Zulu" and i["label"] == "Hall Zulu"
               and i["site_id"] == site["id"] and i["site_name"] == "MatchSite" and set(i) == HALL_KEYS
               for i in halls["items"])
    assert any(i["id"] == row["id"] and i["name"] == "Row Zulu" and i["label"] == "Row Zulu"
               and i["hall_id"] == hall["id"] and i["hall_name"] == "Hall Zulu"
               and i["site_id"] == site["id"] and i["site_name"] == "MatchSite"
               and set(i) == ROW_KEYS for i in rows["items"])

    cabs = client.get("/home/search", params={"q": "r99"}).json()
    cab = next(i for i in _group(cabs, "cabinets")["items"] if i["id"] == rack["id"])
    assert set(cab) == CABINET_KEYS
    assert cab == {
        "id": rack["id"],
        "label": "R99",
        "name": "R99",
        "row_id": row["id"],
        "row_name": "Row Zulu",
        "hall_id": hall["id"],
        "hall_name": "Hall Zulu",
    }


def test_search_default_and_max_limits(client):
    site = client.post("/sites", json={"name": "LimitSite"}).json()
    hall = client.post("/halls", json={"site_id": site["id"], "name": "Limit Hall"}).json()
    row = client.post("/rows", json={"hall_id": hall["id"], "name": "Limit Row"}).json()
    extra = SEARCH_DEFAULT_LIMIT + 2
    racks = []
    for i in range(extra):
        racks.append(client.post("/racks", json={
            "row_id": row["id"], "name": f"LIM-C{i:02d}", "u_height": 42,
        }).json())
    for i in range(SEARCH_MAX_LIMIT + 2):
        r = client.post("/devices", json={"host_name": f"lim-dev-{i:02d}", "status": "install"})
        assert r.status_code == 201, r.text

    defaulted = client.get("/home/search", params={"q": "LIM-C"}).json()
    cabs = _group(defaulted, "cabinets")
    assert cabs["count"] == extra
    assert cabs["truncated"] is True
    assert len(cabs["items"]) == SEARCH_DEFAULT_LIMIT
    assert [i["name"] for i in cabs["items"]] == [f"LIM-C{i:02d}" for i in range(SEARCH_DEFAULT_LIMIT)]

    capped = client.get("/home/search", params={"q": "lim-dev", "limit": SEARCH_MAX_LIMIT}).json()
    devs = _group(capped, "devices")
    assert devs["count"] == SEARCH_MAX_LIMIT + 2
    assert devs["truncated"] is True
    assert len(devs["items"]) == SEARCH_MAX_LIMIT

    untruncated = client.get("/home/search", params={"q": "LIM-C", "limit": 20}).json()
    full = _group(untruncated, "cabinets")
    assert full["count"] == extra and full["truncated"] is False
    assert len(full["items"]) == extra

    assert client.get("/home/search", params={"q": "LIM-C", "limit": SEARCH_MAX_LIMIT + 1}).status_code == 422
    assert client.get("/home/search", params={"q": "LIM-C", "limit": 0}).status_code == 422


def test_search_escapes_like_wildcards(client):
    site, hall, row, rack = _layout(client, site="WildSite", hall="H1", row="R1", rack="W1")
    literal_pct = client.post("/devices", json={"host_name": "ab%cd", "status": "install"}).json()
    literal_us = client.post("/devices", json={"host_name": "ab_cd", "status": "install"}).json()
    filled = client.post("/devices", json={"host_name": "abXcd", "status": "install"}).json()

    pct = client.get("/home/search", params={"q": "ab%"}).json()
    pct_ids = {i["id"] for i in _group(pct, "devices")["items"]}
    assert literal_pct["id"] in pct_ids
    assert literal_us["id"] not in pct_ids
    assert filled["id"] not in pct_ids

    us = client.get("/home/search", params={"q": "ab_"}).json()
    us_ids = {i["id"] for i in _group(us, "devices")["items"]}
    assert literal_us["id"] in us_ids
    assert literal_pct["id"] not in us_ids
    assert filled["id"] not in us_ids


def test_search_q_is_stripped(client):
    client.post("/sites", json={"name": "TrimSite"})
    r = client.get("/home/search", params={"q": "  TrimSite  "})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["query"] == "TrimSite"
    # Trimming must not make a 2-space pad look like a long enough query on its own.
    assert len(body["query"]) >= SEARCH_MIN_CHARS
