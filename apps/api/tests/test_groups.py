def test_group_crud_case_insensitive(client, client_as):
    g = client.post("/groups", json={"name": "Storage Team"})
    assert g.status_code == 201
    assert client.post("/groups", json={"name": "storage team"}).status_code == 409
    assert client.get("/groups?q=stor").json()[0]["name"] == "Storage Team"
    gid = g.json()["id"]
    assert client.patch(f"/groups/{gid}", json={"name": "Storage Ops"}).json()["name"] == "Storage Ops"
    ro = client_as("read-only")
    assert ro.get("/groups").status_code == 200 and ro.post("/groups", json={"name": "x"}).status_code == 403
    assert client_as("technician").delete(f"/groups/{gid}").status_code == 403
    assert client.delete(f"/groups/{gid}").status_code == 204
