from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings


def test_client_request_id_ignored_by_default(client):
    r = client.get("/health", headers={"X-Request-ID": "forged<script>"})
    assert r.headers["X-Request-ID"] != "forged<script>" and len(r.headers["X-Request-ID"]) == 32
    r = client.get("/health", headers={"X-Request-ID": "abc-123"})
    assert r.headers["X-Request-ID"] != "abc-123"


def test_trusted_proxy_id_must_be_well_formed():
    c = TestClient(create_app(Settings(trust_request_id=True)))
    assert c.get("/health", headers={"X-Request-ID": "abc-123"}).headers["X-Request-ID"] == "abc-123"
    bad = c.get("/health", headers={"X-Request-ID": "x" * 65}).headers["X-Request-ID"]
    assert bad != "x" * 65
    assert c.get("/health", headers={"X-Request-ID": "a b"}).headers["X-Request-ID"] != "a b"
