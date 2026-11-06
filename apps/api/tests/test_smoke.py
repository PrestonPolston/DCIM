def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_cors_only_for_configured_origins():
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.settings import Settings

    preflight = {"Origin": "https://ui.example", "Access-Control-Request-Method": "POST"}
    closed = TestClient(create_app(Settings(_env_file=None, trusted_hosts=["testserver"])))
    assert "access-control-allow-origin" not in closed.options("/devices", headers=preflight).headers
    open_ = TestClient(create_app(Settings(_env_file=None, trusted_hosts=["testserver"],
                                           cors_origins=["https://ui.example"])))
    r = open_.options("/devices", headers=preflight)
    assert r.headers["access-control-allow-origin"] == "https://ui.example"
    assert "X-CSRF-Token" in r.headers["access-control-allow-headers"]
    bad = open_.options("/devices", headers={**preflight, "Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in bad.headers


def test_migrations_upgrade_and_downgrade(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config

    monkeypatch.setenv("DCIM_DATABASE_URL", f"sqlite:///{tmp_path / 'mig.db'}")
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
