import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


def make_type(client):
    return client.post("/device-types", json={"manufacturer": "Dell", "name": "R9"}).json()


def test_profile_fields_and_effective_color(client):
    t = make_type(client)
    r = client.post(f"/device-types/{t['id']}/profiles", json={
        "name": "blue", "is_default": True, "color_hex": "#0000FF", "airflow": "front_to_rear",
        "power_type": "AC_DC", "ports": [{"name": "eth0", "speed_mbps": 25000, "x_mm": 10}],
        "power": [{"name": "PSU1", "connector": "C14", "max_draw_w": 800}],
    })
    assert r.status_code == 201, r.text
    assert r.json()["ports"][0]["x_mm"] == 10
    from tests.test_locations import COMPLETE, publish_profile
    publish_profile(client, t["id"], r.json()["id"], {**COMPLETE, "power_type": "AC_DC"})
    d = client.post("/devices", json={"host_name": "x", "device_type_id": t["id"]}).json()
    assert d["effective_color_hex"] == "#0000FF"
    d = client.patch(f"/devices/{d['id']}", json={"color_hex": "#FF0000"}).json()
    assert d["effective_color_hex"] == "#FF0000"


@pytest.mark.parametrize("body", [
    {"airflow": "up"}, {"power_type": "ACDC"}, {"color_hex": "#12345"},
    {"ports": [{"speed_mbps": 10}]}, {"ports": [{"name": "a", "speed_mbps": 0}]}, {"ports": {"a": 1}},
    {"power": [{"name": "p", "voltage": -1}]},
])
def test_invalid_profile_json_422(client, body):
    t = make_type(client)
    assert client.post(f"/device-types/{t['id']}/profiles", json={"name": "p", **body}).status_code == 422


@pytest.mark.parametrize("col,bad", [("color_hex", "'blue'"), ("airflow", "'up'"), ("power_type", "'ACDC'")])
def test_profile_checks(engine, client, col, bad):
    t = make_type(client)
    with engine.begin() as conn:
        conn.execute(text(f"INSERT INTO device_type_profiles (device_type_id, name, u_height, {col}) "
                          f"VALUES ({t['id']}, 'ok', 1, NULL)"))
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text(f"INSERT INTO device_type_profiles (device_type_id, name, u_height, {col}) "
                              f"VALUES ({t['id']}, 'bad', 1, {bad})"))
