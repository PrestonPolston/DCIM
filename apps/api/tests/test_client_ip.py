"""N-1: X-Forwarded-For is only believed from DCIM_TRUSTED_PROXIES."""
import pytest
from starlette.requests import Request

from app.security.client_ip import client_ip
from app.settings import Settings, get_settings
from tests.conftest import login


def req(peer, xff=None):
    headers = [(b"x-forwarded-for", xff.encode())] if xff else []
    return Request({"type": "http", "client": (peer, 1234), "headers": headers})


def test_header_ignored_without_trusted_proxies(monkeypatch):
    monkeypatch.setattr(get_settings(), "trusted_proxies", [])
    assert client_ip(req("127.0.0.1", "6.6.6.6")) == "127.0.0.1"


def test_header_ignored_from_untrusted_peer(monkeypatch):
    monkeypatch.setattr(get_settings(), "trusted_proxies", ["10.0.0.5"])
    assert client_ip(req("192.168.1.9", "6.6.6.6")) == "192.168.1.9"


def test_rightmost_untrusted_hop_from_trusted_proxy(monkeypatch):
    monkeypatch.setattr(get_settings(), "trusted_proxies", ["10.0.0.0/24"])
    # client spoofs 6.6.6.6; the proxy appends the real peer 192.168.1.9
    assert client_ip(req("10.0.0.5", "6.6.6.6, 192.168.1.9")) == "192.168.1.9"
    assert client_ip(req("10.0.0.5", "192.168.1.9, 10.0.0.7")) == "192.168.1.9"
    assert client_ip(req("10.0.0.5", "not-an-ip")) == "10.0.0.5"
    assert client_ip(req("10.0.0.5")) == "10.0.0.5"


def test_bad_trusted_proxy_rejected():
    with pytest.raises(ValueError):
        Settings(trusted_proxies="nope")


def test_spoofed_header_does_not_bypass_ip_limit(anon, make_user, monkeypatch):
    monkeypatch.setattr(get_settings(), "trusted_proxies", [])
    monkeypatch.setattr(get_settings(), "login_rate_per_ip", 3)
    make_user("admin", email="a@example.com")
    codes = []
    for i in range(5):
        anon.headers["X-Forwarded-For"] = f"6.6.6.{i}"
        codes.append(login(anon, "a@example.com", "wrong-password-xx").status_code)
    assert codes[-1] == 429


def test_launcher_disables_proxy_headers():
    import pathlib
    src = pathlib.Path(__file__).parents[1].joinpath("app", "__main__.py").read_text()
    assert "proxy_headers=False" in src
