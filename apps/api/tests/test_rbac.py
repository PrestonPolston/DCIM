import re

import pytest

from app.main import PUBLIC_PATHS, app
from tests.test_locations import dtype, make_rack, place


def all_operations():
    """Every route actually mounted (R-10: walks app.routes, so include_in_schema=False can't hide one)."""
    from starlette.routing import Mount

    def walk(routes, prefix=""):
        for r in routes:
            if isinstance(r, Mount):
                yield from walk(r.routes, prefix + r.path)
            elif hasattr(r, "original_router"):  # FastAPI include_router wrapper
                yield from walk(r.original_router.routes, prefix)
            elif getattr(r, "methods", None):
                for m in r.methods - {"HEAD", "OPTIONS"}:
                    yield m, prefix + r.path

    seen = set(walk(app.routes))
    schema = {(m.upper(), p) for p, ops in app.openapi()["paths"].items() for m in ops}
    assert schema <= seen
    yield from sorted(seen)


def test_every_non_public_route_requires_auth(anon):
    """Route coverage: deny by default. Fails if a new route forgets the auth dependency."""
    checked = 0
    for method, path in all_operations():
        if path in PUBLIC_PATHS:
            continue
        url = re.sub(r"\{[^}]+\}", "1", path)
        r = anon.request(method, url)
        assert r.status_code == 401, f"{method} {path} -> {r.status_code}"
        checked += 1
    assert checked > 40


def test_public_routes(anon):
    for path in ("/", "/health", "/version", "/auth/providers"):
        assert anon.get(path).status_code == 200


@pytest.fixture
def world(client):
    """Admin-created fixtures: site/hall/row/rack, a device type and a racked device."""
    rack = make_rack(client)
    dt = dtype(client, 1)
    device = place(client, rack, dt, 1, host="web-01").json()
    return {"rack": rack, "dt": dt, "device": device}


# (role, method, url template, json, expected status)
MATRIX = [
    ("read-only", "GET", "/devices", None, 200),
    ("read-only", "GET", "/devices/export", None, 200),
    ("read-only", "GET", "/racks/{rack}/elevation", None, 200),
    ("read-only", "POST", "/devices", {"host_name": "x"}, 403),
    ("read-only", "PATCH", "/devices/{device}", {"status": "decom"}, 403),
    ("read-only", "POST", "/device-types", {"manufacturer": "A", "name": "B"}, 403),
    ("read-only", "PATCH", "/racks/{rack}", {"pos_x": 1}, 403),
    ("read-only", "GET", "/users", None, 403),
    ("technician", "POST", "/devices", {"host_name": "x"}, 201),
    ("technician", "PATCH", "/devices/{device}", {"status": "decom"}, 200),
    ("technician", "DELETE", "/devices/{device}", None, 403),
    ("technician", "POST", "/device-types", {"manufacturer": "A", "name": "B"}, 201),
    ("technician", "PATCH", "/device-types/{dt}", {"name": "C"}, 403),
    ("technician", "DELETE", "/device-types/{dt}", None, 403),
    ("technician", "PATCH", "/racks/{rack}", {"pos_x": 3, "pos_y": 4, "orientation": "E"}, 200),
    ("technician", "PATCH", "/racks/{rack}", {"u_height": 40}, 403),
    ("technician", "PATCH", "/racks/{rack}", {"name": "new"}, 403),
    ("technician", "POST", "/racks", {"row_id": 1, "name": "R9"}, 403),
    ("technician", "DELETE", "/racks/{rack}", None, 403),
    ("technician", "POST", "/sites", {"name": "S2"}, 403),
    ("technician", "GET", "/audit-events", None, 403),
    ("technician", "POST", "/users", {"email": "a@b.c", "role": "admin"}, 403),
    ("admin", "DELETE", "/devices/{device}", None, 204),
    ("admin", "PATCH", "/racks/{rack}", {"u_height": 40}, 200),
    ("admin", "POST", "/sites", {"name": "S2"}, 201),
    ("admin", "GET", "/audit-events", None, 200),
]


@pytest.mark.parametrize("role,method,url,body,expected", MATRIX)
def test_role_matrix(world, client_as, role, method, url, body, expected):
    c = client_as(role)
    url = url.format(rack=world["rack"]["id"], device=world["device"]["id"], dt=world["dt"]["id"])
    r = c.request(method, url, json=body)
    assert r.status_code == expected, r.text


def test_import_roles(world, client_as):
    body = "host_name\nimported-1\n"
    headers = {"Content-Type": "text/csv"}
    ro = client_as("read-only")
    assert ro.post("/devices/import", content=body, headers=headers).status_code == 403
    tech = client_as("technician")
    r = tech.post("/devices/import?dry_run=false", content=body, headers=headers)
    assert r.status_code == 200 and r.json()["created"] == 1
