import os

# Test settings must be in place before the app (and its cached settings) is imported
os.environ.setdefault("DCIM_TRUSTED_HOSTS", "testserver,localhost,127.0.0.1")
os.environ.setdefault("DCIM_ENV", "dev")

import pytest  # noqa: E402
from argon2 import PasswordHasher  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session, SQLModel  # noqa: E402

import app.models  # noqa: E402,F401  (registers tables)
from app.db import get_session, make_engine  # noqa: E402
from app.main import app  # noqa: E402
from app.modules.audit.guards import create_append_only_guards  # noqa: E402
from app.modules.auth import passwords  # noqa: E402
from app.modules.auth.models import UserRow  # noqa: E402

PASSWORD = "correct-horse-battery-42"
# Set to a postgresql+psycopg:// URL to run the suite on Postgres (CI does); default: temp SQLite files
TEST_DATABASE_URL = os.environ.get("DCIM_TEST_DATABASE_URL")


def reset_postgres(url: str) -> None:
    from sqlalchemy import create_engine

    eng = create_engine(url)
    with eng.begin() as conn:
        conn.exec_driver_sql("DROP SCHEMA public CASCADE")
        conn.exec_driver_sql("CREATE SCHEMA public")
    eng.dispose()


@pytest.fixture(autouse=True)
def fast_hashing(monkeypatch):
    # argon2id with tiny costs so the suite stays fast (production params tested separately)
    monkeypatch.setattr(passwords, "hasher", PasswordHasher(time_cost=1, memory_cost=8, parallelism=1))
    monkeypatch.setattr(passwords, "_DUMMY_HASH", None)
    from app.security.ratelimit import login_limiter
    login_limiter.reset()
    from app.modules.images.router import upload_limiter
    upload_limiter.reset()


@pytest.fixture
def engine(tmp_path, request):
    # @pytest.mark.pre_p1_18: build the schema with devices.profile_id nullable (legacy rows for the
    # removal/restore scripts and needs_review flag tests)
    from app.modules.devices.models import DeviceRow
    legacy = request.node.get_closest_marker("pre_p1_18") is not None
    DeviceRow.__table__.c.profile_id.nullable = legacy
    if TEST_DATABASE_URL:
        reset_postgres(TEST_DATABASE_URL)
        engine = make_engine(TEST_DATABASE_URL)
    else:
        engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    SQLModel.metadata.create_all(engine)
    DeviceRow.__table__.c.profile_id.nullable = False
    with engine.begin() as conn:
        create_append_only_guards(conn)

    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    yield engine
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture
def make_user(engine):
    def _make(role="admin", email=None, password=PASSWORD, must_change_password=False, **kw):
        with Session(engine) as session:
            user = UserRow(email=email or f"{role}@example.com", role=role,
                           password_hash=passwords.hash_password(password),
                           must_change_password=must_change_password, **kw)
            session.add(user)
            session.commit()
            session.refresh(user)
            return user
    return _make


def login(client: TestClient, email: str, password: str = PASSWORD):
    r = client.post("/auth/login", json={"email": email, "password": password})
    if r.status_code == 200:
        client.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    return r


@pytest.fixture
def client_as(engine, make_user):
    clients = []

    def _client(role="admin", email=None):
        c = TestClient(app)
        clients.append(c)
        if role is not None:
            user = make_user(role, email=email or f"{role}{len(clients)}@example.com")
            assert login(c, user.email).status_code == 200
        return c

    yield _client
    for c in clients:
        c.close()


# Default client: logged in as admin (existing feature tests)
@pytest.fixture
def client(client_as):
    return client_as("admin")


@pytest.fixture
def anon(engine):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def no_login_rate_limit(monkeypatch):
    from app.settings import get_settings
    for name in ("login_rate_per_ip", "login_failures_per_ip_email", "login_rate_global"):
        monkeypatch.setattr(get_settings(), name, 0)


# D36 (p1_17): every new device needs a published profile. Most older tests are about other rules and
# create devices with only host_name; this shim gives those requests a published "Generic 1U" profile.
# Tests about the profile rule opt out with the header X-Test-Raw: 1 (stripped before sending).
GENERIC = {}


def generic_profile_id(engine) -> tuple[int, int]:
    key = id(engine)
    if key not in GENERIC:
        from datetime import UTC, datetime
        from app.modules.device_types.models import DeviceTypeProfileRow, DeviceTypeRow
        with Session(engine) as s:
            t = DeviceTypeRow(manufacturer="Generic", name="Test 1U", u_height=1, is_full_depth=True,
                              asset_type="other")
            s.add(t)
            s.flush()
            p = DeviceTypeProfileRow(device_type_id=t.id, name="default", is_default=True, u_height=1,
                                     width_mm=482.6, height_mm=44, depth_mm=600, power_type="AC",
                                     mounting="rack_19in", status="published", published_at=datetime.now(UTC))
            s.add(p)
            s.flush()
            # complete + usable: front and rear images (rows written directly, no audit noise)
            import io
            from PIL import Image
            from app.modules.images import service as img_service
            from app.modules.images.models import ProfileImageRow
            buf = io.BytesIO()
            Image.new("RGB", (8, 4), (90, 90, 90)).save(buf, "PNG")
            processed = img_service.process(buf.getvalue(), "image/png")
            for face in ("front", "rear"):
                for variant, info in processed.items():
                    s.add(ProfileImageRow(profile_id=p.id, face=face, variant=variant, **info))
            s.commit()
            GENERIC[key] = (t.id, p.id)
    return GENERIC[key]


@pytest.fixture(autouse=True)
def default_profile_shim(request, monkeypatch):
    original = TestClient.request

    def patched(self, method, url, *args, **kwargs):
        headers = dict(kwargs.get("headers") or {})
        raw = headers.pop("X-Test-Raw", None) or headers.pop("x-test-raw", None)
        if kwargs.get("headers") is not None:
            kwargs["headers"] = headers
        path = str(url).split("?")[0]
        if not raw and method.upper() == "POST" and path == "/devices" and isinstance(kwargs.get("json"), dict):
            body = kwargs["json"]
            if not ({"device_type_id", "profile_id"} & set(body)):
                kwargs["json"] = {**body, "profile_id": generic_profile_id(request.getfixturevalue("engine"))[1]}
        elif not raw and method.upper() == "POST" and path == "/devices/import" and kwargs.get("content"):
            content = kwargs["content"]
            try:
                text = content.decode() if isinstance(content, bytes) else content
            except UnicodeDecodeError:
                return original(self, method, url, *args, **kwargs)
            lines = text.split("\n")
            head = [h.strip().lstrip("\ufeff").lower() for h in lines[0].split(",")]
            if not ({"device_type_id", "profile_id", "manufacturer"} & set(head)) and "host_name" in head:
                tid = generic_profile_id(request.getfixturevalue("engine"))[1]
                def add(ln, v):
                    cr = "\r" if ln.endswith("\r") else ""
                    return ln[:len(ln) - len(cr)] + f",{v}" + cr
                lines = [add(lines[0], "profile_id")] + [add(ln, tid) if ln.strip() else ln for ln in lines[1:]]
                new = "\n".join(lines)
                kwargs["content"] = new.encode() if isinstance(content, bytes) else new
        return original(self, method, url, *args, **kwargs)

    monkeypatch.setattr(TestClient, "request", patched)
    yield
    GENERIC.clear()


def pytest_configure(config):
    config.addinivalue_line("markers", "pre_p1_18: schema with nullable devices.profile_id (legacy data tests)")
