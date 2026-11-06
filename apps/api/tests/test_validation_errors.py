SECRET = "Sup3r-S3cret-Value-xyz"


def test_422_does_not_echo_input(client):
    r = client.post("/devices", json={"host_name": "a", "ilo_password": SECRET})
    assert r.status_code == 422
    assert SECRET not in r.text
    assert set(r.json()["detail"][0]) == {"type", "loc", "msg"}


def test_login_long_password_not_echoed(anon):
    long_pw = "P" * 300 + SECRET
    r = anon.post("/auth/login", json={"email": "x@example.com", "password": long_pw})
    assert r.status_code == 422 and SECRET not in r.text


def test_change_password_not_echoed(client):
    r = client.post("/auth/change-password", json={"current_password": SECRET * 20, "new_password": "x"})
    assert r.status_code == 422 and SECRET not in r.text
