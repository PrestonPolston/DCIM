import pytest
from pydantic import ValidationError

from app.settings import Settings


def test_defaults_are_lan_safe(monkeypatch):
    for key in ("DCIM_ENV", "DCIM_CORS_ORIGINS", "DCIM_COOKIE_SECURE", "DCIM_TRUSTED_HOSTS"):
        monkeypatch.delenv(key, raising=False)
    s = Settings(_env_file=None)
    assert s.cookie_secure is False and s.cors_origins == [] and s.bind_host == "127.0.0.1"
    assert "localhost" in s.trusted_hosts and s.docs_enabled is True


def test_prod_fails_closed():
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(_env_file=None, env="prod")
    strong = "x" * 40
    with pytest.raises(ValidationError, match="Wildcards"):
        Settings(_env_file=None, env="prod", secret_key=strong, cors_origins=["*"])
    s = Settings(_env_file=None, env="prod", secret_key=strong)
    assert s.cookie_secure is True and s.docs_enabled is False
    assert s.session_cookie_name == "__Host-dcim_session"


def test_unknown_provider_rejected():
    with pytest.raises(ValidationError, match="OIDC"):
        Settings(_env_file=None, auth_providers=["local", "entra"])


def test_comma_separated_env(monkeypatch):
    monkeypatch.setenv("DCIM_CORS_ORIGINS", "https://a.example, https://b.example")
    assert Settings(_env_file=None).cors_origins == ["https://a.example", "https://b.example"]


def test_docs_off_when_dev_binds_to_lan():
    from app.settings import Settings
    # N-6: bind_host no longer decides; DCIM_ENV (or an explicit DCIM_DOCS_ENABLED) does
    assert Settings(env="dev", bind_host="0.0.0.0").docs_enabled is True
    assert Settings(env="dev", docs_enabled=False).docs_enabled is False
    assert Settings(env="prod", secret_key="x" * 40, docs_enabled=True).docs_enabled is True
    assert Settings(env="dev", bind_host="0.0.0.0", docs_enabled=True).docs_enabled is True
    assert Settings(env="dev").docs_enabled is True
