from datetime import timedelta

from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import app
from app.modules.audit.models import AuditEventRow
from app.modules.auth import passwords
from app.modules.auth.models import SessionRow, UserRow
from app.timestamps import utcnow
from tests.conftest import PASSWORD, login


def actions(engine):
    with Session(engine) as s:
        return [e.action for e in s.exec(select(AuditEventRow).order_by(AuditEventRow.id)).all()]


def test_login_sets_secure_cookie_and_me(anon, make_user):
    make_user("technician", email="tech@example.com")
    r = login(anon, "TECH@example.com")
    assert r.status_code == 200
    cookie = r.headers["set-cookie"]
    assert "dcim_session=" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/" in cookie
    assert "Secure" not in cookie  # COOKIE_SECURE defaults to false (LAN/dev)
    me = anon.get("/auth/me").json()
    assert me["email"] == "tech@example.com" and me["role"] == "technician" and me["csrf_token"]


def test_production_hash_parameters():
    h = passwords.PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4).hash("x" * 12)
    assert h.startswith("$argon2id$v=19$m=65536,t=3,p=4$")


def test_stored_hash_is_argon2id(make_user):
    assert make_user().password_hash.startswith("$argon2id$")


def test_rehash_on_login_when_params_change(anon, make_user, engine, monkeypatch):
    user = make_user("read-only")
    monkeypatch.setattr(passwords, "hasher", PasswordHasher(time_cost=2, memory_cost=16, parallelism=1))
    assert login(anon, user.email).status_code == 200
    with Session(engine) as s:
        assert "t=2" in s.get(UserRow, user.id).password_hash


def test_wrong_password_and_unknown_email_are_generic(anon, make_user, engine):
    make_user("admin")
    a = login(anon, "admin@example.com", "wrong-password-123")
    b = login(anon, "nobody@example.com", "wrong-password-123")
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json() == {"detail": "Invalid email or password"}
    assert actions(engine).count("auth.login_failed") == 2


def test_lockout_after_max_failures(no_login_rate_limit, anon, make_user, engine):
    user = make_user("admin")
    for _ in range(10):
        login(anon, user.email, "wrong-password-123")
    assert "auth.locked" in actions(engine)
    assert login(anon, user.email).status_code == 401  # correct password, still locked
    with Session(engine) as s:
        u = s.get(UserRow, user.id)
        u.locked_until = utcnow() - timedelta(seconds=1)
        s.commit()
    assert login(anon, user.email).status_code == 200


def test_inactive_user_cannot_login(anon, make_user):
    make_user("admin", is_active=False)
    assert login(anon, "admin@example.com").status_code == 401


def test_logout_kills_session(anon, make_user, engine):
    make_user("admin")
    login(anon, "admin@example.com")
    assert anon.post("/auth/logout").status_code == 204
    assert anon.get("/auth/me").status_code == 401
    with Session(engine) as s:
        assert s.exec(select(SessionRow)).all() == []


def test_session_id_rotates_and_token_not_stored(anon, make_user, engine):
    make_user("admin")
    login(anon, "admin@example.com")
    first = anon.cookies.get("dcim_session")
    login(anon, "admin@example.com")
    assert anon.cookies.get("dcim_session") != first
    with Session(engine) as s:
        ids = [r.id for r in s.exec(select(SessionRow)).all()]
    assert first not in ids and all(len(i) == 64 for i in ids)  # sha256 hex only


def test_expired_and_idle_sessions_rejected(anon, make_user, engine):
    make_user("admin")
    login(anon, "admin@example.com")
    with Session(engine) as s:
        row = s.exec(select(SessionRow)).one()
        row.last_seen_at = utcnow() - timedelta(hours=9)  # idle limit 8h
        s.commit()
    assert anon.get("/auth/me").status_code == 401
    login(anon, "admin@example.com")
    with Session(engine) as s:
        row = s.exec(select(SessionRow)).one()
        row.expires_at = utcnow() - timedelta(seconds=1)
        s.commit()
    assert anon.get("/devices").status_code == 401


def test_must_change_password_flow(anon, make_user):
    make_user("technician", email="new@example.com", must_change_password=True)
    login(anon, "new@example.com")
    r = anon.get("/devices")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "password_change_required"
    assert anon.get("/auth/me").json()["must_change_password"] is True
    weak = anon.post("/auth/change-password", json={"current_password": PASSWORD, "new_password": "short"})
    assert weak.status_code == 422
    common = anon.post("/auth/change-password", json={"current_password": PASSWORD, "new_password": "password1234"})
    assert "too common" in str(common.json())
    has_email = anon.post("/auth/change-password", json={"current_password": PASSWORD, "new_password": "new@example.com"})
    assert has_email.status_code == 422
    ok = anon.post("/auth/change-password",
                   json={"current_password": PASSWORD, "new_password": "a-much-better-passphrase"})
    assert ok.status_code == 200 and ok.json()["must_change_password"] is False
    assert anon.get("/devices").status_code == 200


def test_change_password_requires_current(client):
    r = client.post("/auth/change-password", json={"current_password": "nope", "new_password": "another-long-pass-1"})
    assert r.status_code == 400


def test_providers_public(anon):
    assert anon.get("/auth/providers").json() == [{"id": "local", "kind": "password", "name": "Email and password"}]


def test_csrf_required_on_unsafe_methods(client):
    token = client.headers.pop("X-CSRF-Token")
    assert client.post("/sites", json={"name": "A"}).status_code == 403
    assert client.post("/sites", json={"name": "A"}, headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert client.post("/sites", json={"name": "A"}, headers={"X-CSRF-Token": token}).status_code == 201
    # text/csv import is a "simple" CORS request, so it must need the token too
    r = client.post("/devices/import", content="host_name\na\n", headers={"Content-Type": "text/csv"})
    assert r.status_code == 403
    assert client.get("/sites").status_code == 200  # safe methods need no token


def test_foreign_origin_rejected(client, anon, make_user):
    assert client.post("/sites", json={"name": "A"}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/sites", json={"name": "B"}, headers={"Origin": "http://localhost:5173"}).status_code == 201
    assert client.post("/sites", json={"name": "C"}, headers={"Referer": "https://evil.example/x"}).status_code == 403
    make_user("read-only")
    r = anon.post("/auth/login", json={"email": "read-only@example.com", "password": PASSWORD},
                  headers={"Origin": "https://evil.example"})
    assert r.status_code == 403  # login CSRF


def test_login_and_logout_audited(anon, make_user, engine):
    make_user("admin")
    login(anon, "admin@example.com")
    anon.post("/auth/logout")
    assert actions(engine) == ["auth.login", "auth.logout"]


def test_no_self_signup(anon):
    paths = set(app.openapi()["paths"])
    assert not any("signup" in p or "register" in p for p in paths)
    assert anon.post("/users", json={"email": "x@example.com", "role": "admin"}).status_code in (401, 403)


def test_security_headers(anon):
    r = anon.get("/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    assert r.headers["Cache-Control"] == "no-store" and r.headers["X-Request-ID"]
    assert "Strict-Transport-Security" not in r.headers


def test_hsts_and_trusted_hosts():
    from app.main import create_app
    from app.settings import Settings

    c = TestClient(create_app(Settings(_env_file=None, hsts_enabled=True, trusted_hosts=["testserver"])),
                   base_url="https://testserver")
    r = c.get("/health")
    assert r.headers["Strict-Transport-Security"] == "max-age=86400"  # short LAN default, no subdomains
    assert r.headers["Permissions-Policy"].startswith("camera=()")
    http = TestClient(create_app(Settings(_env_file=None, hsts_enabled=True, trusted_hosts=["testserver"])))
    assert "Strict-Transport-Security" not in http.get("/health").headers  # off unless HTTPS
    long = TestClient(create_app(Settings(_env_file=None, hsts_enabled=True, hsts_max_age=31536000,
                                          hsts_include_subdomains=True, permissions_camera_self=True,
                                          trusted_hosts=["testserver"])), base_url="https://testserver")
    r = long.get("/health")
    assert r.headers["Strict-Transport-Security"] == "max-age=31536000; includeSubDomains"
    assert r.headers["Permissions-Policy"] == "camera=(self), microphone=(), geolocation=()"
    off = TestClient(create_app(Settings(_env_file=None, trusted_hosts=["testserver"])), base_url="https://testserver")
    assert "Strict-Transport-Security" not in off.get("/health").headers
    bad = TestClient(create_app(Settings(_env_file=None, trusted_hosts=["dcim.example"])))
    assert bad.get("/health").status_code == 400


def test_docs_disabled_in_prod():
    from app.main import create_app
    from app.settings import Settings

    c = TestClient(create_app(Settings(_env_file=None, env="prod", secret_key="x" * 40, trusted_hosts=["testserver"])))
    assert c.get("/docs").status_code == 404 and c.get("/openapi.json").status_code == 404


def test_password_change_rotates_session(anon, make_user):
    from app.settings import get_settings

    make_user("technician", email="rot@example.com")
    login(anon, "rot@example.com")
    name = get_settings().session_cookie_name
    old_cookie, old_csrf = anon.cookies.get(name), anon.headers["X-CSRF-Token"]
    r = anon.post("/auth/change-password", json={"current_password": PASSWORD, "new_password": "rotated-passphrase-77"})
    assert r.status_code == 200
    new_cookie = anon.cookies.get(name)
    assert new_cookie and new_cookie != old_cookie and r.json()["csrf_token"] != old_csrf
    assert anon.get("/auth/me").status_code == 200  # new session works
    anon.cookies.set(name, old_cookie)
    assert anon.get("/auth/me").status_code == 401  # old one is gone
