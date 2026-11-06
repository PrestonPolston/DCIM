from app.settings import get_settings


def login(c, email, pw, ip=None):
    return c.post("/auth/login", json={"email": email, "password": pw})


def test_failures_per_ip_email_limited(anon, make_user):
    user = make_user("technician")
    for _ in range(get_settings().login_failures_per_ip_email):
        assert login(anon, user.email, "wrong-password-123").status_code == 401
    r = login(anon, user.email, "wrong-password-123")
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1
    # another account from the same IP is still allowed (until the per-IP cap)
    other = make_user("read-only")
    assert login(anon, other.email, "wrong-password-123").status_code == 401


def test_per_ip_cap_counts_all_attempts(anon, make_user, monkeypatch):
    monkeypatch.setattr(get_settings(), "login_rate_per_ip", 3)
    for i in range(3):
        assert login(anon, f"nobody{i}@example.com", "x" * 12).status_code == 401
    assert login(anon, "nobody9@example.com", "x" * 12).status_code == 429


def test_rate_limited_event_audited(anon, engine, monkeypatch):
    from sqlmodel import Session, select
    from app.modules.audit.models import AuditEventRow

    monkeypatch.setattr(get_settings(), "login_rate_per_ip", 1)
    login(anon, "a@example.com", "x" * 12)
    assert login(anon, "a@example.com", "x" * 12).status_code == 429
    with Session(engine) as s:
        assert s.exec(select(AuditEventRow).where(AuditEventRow.action == "auth.rate_limited")).first()


def test_n2_one_rate_limited_audit_per_window(anon, engine, monkeypatch):
    from sqlmodel import Session, func, select
    from app.modules.audit.models import AuditEventRow

    monkeypatch.setattr(get_settings(), "login_rate_per_ip", 1)
    login(anon, "a@example.com", "x" * 12)
    for _ in range(25):
        assert login(anon, "a@example.com", "x" * 12).status_code == 429
    with Session(engine) as s:
        n = s.exec(select(func.count()).select_from(AuditEventRow)
                   .where(AuditEventRow.action == "auth.rate_limited")).one()
    assert n == 1


def test_n3_limiter_keys_bounded():
    from app.security.ratelimit import SlidingWindow
    lim = SlidingWindow(max_keys=100)
    for i in range(1000):
        lim.retry_after(f"ip:{i}", 5, 60)
    assert len(lim) <= 100
    assert lim.blocked("never-seen", 1, 60) == 0 and len(lim) <= 100  # reads create no keys
    lim2 = SlidingWindow(max_keys=10)
    for i in range(50):
        lim2.retry_after(f"k{i}", 5, 0.0001)  # expired entries are dropped first
    assert len(lim2) <= 10
    for i in range(500):
        lim.first_in_window(f"audit:{i}", 60)
    assert len(lim._noted) <= 100


def test_r12_admin_only_refusal_audited(anon, engine, make_user, monkeypatch):
    import json
    from sqlmodel import Session, select
    from app.modules.audit.models import AuditEventRow

    tech = make_user("technician")
    monkeypatch.setattr(get_settings(), "auth_local_enabled", "admin_only")
    from tests.conftest import PASSWORD
    assert login(anon, tech.email, PASSWORD).status_code == 401
    with Session(engine) as s:
        ev = s.exec(select(AuditEventRow).where(AuditEventRow.action == "auth.login_failed")).all()
    assert [json.loads(e.after_json)["reason"] for e in ev] == ["local_disabled"] and ev[0].entity_id == tech.id


def test_r8_trusted_host_rejection_has_headers():
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.settings import Settings
    bad = TestClient(create_app(Settings(_env_file=None, trusted_hosts=["dcim.example"])))
    r = bad.get("/health")
    assert r.status_code == 400
    assert r.headers["X-Content-Type-Options"] == "nosniff" and r.headers["X-Frame-Options"] == "DENY"
    assert "Content-Security-Policy" in r.headers


def test_n4_validation_input_never_logged(caplog):
    import logging
    from pydantic import BaseModel, ValidationError
    from app.security.logredact import RedactValidationInput, redact

    class M(BaseModel):
        n: int
    try:
        M(n="hunter2-secret")
    except ValidationError as exc:
        err = exc
    assert "hunter2-secret" in str(err) and "hunter2-secret" not in redact(str(err))
    log = logging.getLogger("n4test")
    log.addFilter(RedactValidationInput())
    with caplog.at_level(logging.INFO, logger="n4test"):
        log.info("bad body: %s", err)
        try:
            raise err
        except ValidationError:
            log.exception("boom")
    assert "hunter2-secret" not in caplog.text and "<redacted>" in caplog.text
