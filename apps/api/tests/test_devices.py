def test_device_crud(client):
    r = client.post("/devices", json={"host_name": "web-01", "rack": "R1"})
    assert r.status_code == 201
    dev = r.json()
    assert dev["status"] == "install"

    assert client.get(f"/devices/{dev['id']}").json()["host_name"] == "web-01"
    r = client.patch(f"/devices/{dev['id']}", json={"status": "decom"})
    assert r.json()["status"] == "decom"
    assert client.delete(f"/devices/{dev['id']}").status_code == 204
    assert client.get(f"/devices/{dev['id']}").status_code == 404
