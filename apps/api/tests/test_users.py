from sqlmodel import Session, select

from app.modules.audit.models import AuditEventRow
from tests.conftest import login


def test_admin_creates_user_with_temp_password(client, anon):
    r = client.post("/users", json={"email": "New.Tech@Example.com", "role": "technician"})
    body = r.json()
    assert r.status_code == 201 and body["email"] == "new.tech@example.com" and body["must_change_password"]
    assert len(body["temporary_password"]) >= 16
    assert login(anon, "new.tech@example.com", body["temporary_password"]).json()["must_change_password"] is True
    assert client.post("/users", json={"email": "new.tech@example.com", "role": "admin"}).status_code == 409
    weak = client.post("/users", json={"email": "x@example.com", "role": "admin", "temporary_password": "short"})
    assert weak.status_code == 422


def _user_client(client, anon, role="technician"):
    created = client.post("/users", json={"email": f"{role}-u@example.com", "role": role,
                                          "temporary_password": "temporary-pass-123"}).json()
    login(anon, created["email"], "temporary-pass-123")
    anon.post("/auth/change-password", json={"current_password": "temporary-pass-123",
                                             "new_password": "settled-pass-phrase-9"})
    return created


def test_role_change_and_deactivate_revoke_sessions(client, anon):
    user = _user_client(client, anon)
    assert anon.get("/devices").status_code == 200
    assert client.patch(f"/users/{user['id']}", json={"role": "read-only"}).json()["role"] == "read-only"
    assert anon.get("/devices").status_code == 401
    login(anon, user["email"], "settled-pass-phrase-9")
    assert anon.get("/auth/me").json()["role"] == "read-only"
    client.patch(f"/users/{user['id']}", json={"is_active": False})
    assert anon.get("/devices").status_code == 401
    assert login(anon, user["email"], "settled-pass-phrase-9").status_code == 401


def test_reset_password_revokes_and_forces_change(client, anon):
    user = _user_client(client, anon)
    r = client.post(f"/users/{user['id']}/reset-password").json()
    assert anon.get("/devices").status_code == 401
    assert login(anon, user["email"], r["temporary_password"]).json()["must_change_password"] is True


def test_unlock(no_login_rate_limit, client, anon):
    user = _user_client(client, anon)
    for _ in range(10):
        login(anon, user["email"], "wrong-password-xx")
    assert login(anon, user["email"], "settled-pass-phrase-9").status_code == 401
    client.post(f"/users/{user['id']}/unlock")
    assert login(anon, user["email"], "settled-pass-phrase-9").status_code == 200


def test_cannot_remove_last_admin(client):
    me = client.get("/auth/me").json()
    assert client.patch(f"/users/{me['id']}", json={"role": "technician"}).status_code == 409
    assert client.patch(f"/users/{me['id']}", json={"is_active": False}).status_code == 409


def test_user_admin_actions_audited(client, anon, engine):
    user = _user_client(client, anon)
    client.patch(f"/users/{user['id']}", json={"role": "read-only"})
    with Session(engine) as s:
        acts = [e.action for e in s.exec(select(AuditEventRow)).all()]
    assert "user.create" in acts and "user.role_change" in acts


def test_create_admin_script(engine, monkeypatch, capsys):
    import io

    from app.scripts import create_admin

    monkeypatch.setattr(create_admin, "engine", engine)
    monkeypatch.setattr("sys.stdin", io.StringIO("unrelated-pass-phrase-1\n"))
    assert create_admin.main(["--email", "Boot@Example.com", "--password-stdin"]) == 0
    monkeypatch.setattr("sys.stdin", io.StringIO("short\n"))
    assert create_admin.main(["--email", "b2@example.com", "--password-stdin"]) == 1


def test_user_create_and_audit_are_one_transaction(client, engine, monkeypatch):
    import pytest
    from sqlmodel import Session, select
    from app.modules.auth.models import UserRow
    from app.modules.users import router as users_router

    def boom(*a, **k):
        raise RuntimeError("audit failed")

    monkeypatch.setattr(users_router, "audit", boom)
    with pytest.raises(RuntimeError):
        client.post("/users", json={"email": "atomic@example.com", "display_name": "A", "role": "read-only"})
    with Session(engine) as s:
        assert s.exec(select(UserRow).where(UserRow.email == "atomic@example.com")).first() is None
