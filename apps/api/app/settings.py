from functools import lru_cache
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from typing_extensions import Annotated

WEAK_SECRETS = {"", "change-me", "changeme", "secret", "dev-secret-not-for-production"}
CsvList = Annotated[list[str], NoDecode]


# All configuration comes from DCIM_* environment variables (or apps/api/.env)
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DCIM_", env_file=".env", extra="ignore")

    env: Literal["dev", "prod"] = "dev"
    database_url: str = "sqlite:///./dcim.db"
    secret_key: str = "dev-secret-not-for-production"
    bind_host: str = "127.0.0.1"  # used by `python -m app`
    port: int = 8000
    # N-1: proxies whose X-Forwarded-For is believed (IPs/CIDRs, comma list); empty = ignore the header
    trusted_proxies: CsvList = []

    # cookies / browser security
    cookie_secure: bool = False  # forced on in prod
    cors_origins: CsvList = []  # cross-origin callers (none needed with the Vite proxy)
    trusted_origins: CsvList = ["http://localhost:5173", "http://127.0.0.1:5173"]  # CSRF Origin check
    trusted_hosts: CsvList = ["localhost", "127.0.0.1", "::1"]
    hsts_enabled: bool = False  # sent only on HTTPS requests
    hsts_max_age: int = 86400  # short default for LAN use (LAN_HTTPS_PLAN §7)
    hsts_include_subdomains: bool = False
    permissions_camera_self: bool = False  # camera=(self) for scanning; default camera=()
    docs_enabled: bool | None = None  # default: on in dev, off in prod

    # auth
    auth_providers: CsvList = ["local"]
    auth_local_enabled: Literal["true", "false", "admin_only"] = "true"
    password_min_length: int = 12
    login_max_failures: int = 10
    login_lockout_minutes: int = 15
    # R-2 per-IP login rate limits (0 disables a limit); window in seconds
    login_rate_window_seconds: int = 60
    login_rate_per_ip: int = 10  # all login attempts from one IP
    login_failures_per_ip_email: int = 5  # failed attempts for one IP+email pair
    login_rate_global: int = 300  # all login attempts, any IP
    session_idle_minutes: int = 480
    session_absolute_hours: int = 168

    # audit / CSV
    trust_request_id: bool = False  # accept X-Request-ID from a trusted proxy ([A-Za-z0-9-]{1,64})
    hard_delete_enabled: bool = False  # admin ?hard=true on DELETE /devices; off until DB Architect R1 approved
    audit_retention_months: int = 13  # 0 = keep forever
    # 47e: 'restorable' rows (deletion snapshots) are kept max(24, this) months; 0 = keep forever
    restorable_retention_months: int = 24
    # Removal exports (item 47f): directory outside the repo and any web root; created/required 0700.
    # Unset = --export is refused.
    export_dir: str | None = None
    csv_max_bytes: int = 5 * 1024 * 1024
    csv_max_rows: int = 10_000
    csv_max_field_chars: int = 10_000
    # profile images (items 25/26); the DB CHECKs are the hard ceiling (2 MiB, 4096 px)
    image_max_bytes: int = 2 * 1024 * 1024
    image_max_px: int = 4096
    image_max_pixels: int = 16_000_000
    image_uploads_per_minute: int = 30  # per user; 0 disables
    image_decode_concurrency: int = 4  # F-2: concurrent decodes per process
    image_decode_wait_seconds: float = 10.0  # then 503 image_busy

    @field_validator("cors_origins", "trusted_origins", "trusted_hosts", "auth_providers", "trusted_proxies", mode="before")
    @classmethod
    def _split(cls, value):
        if isinstance(value, str):
            return [v.strip() for v in value.split(",") if v.strip()]
        return value

    @model_validator(mode="after")
    def _fail_closed(self):
        unknown = set(self.auth_providers) - {"local"}
        if unknown:
            raise ValueError(f"Unsupported auth providers (OIDC is not implemented yet): {sorted(unknown)}")
        if self.password_min_length < 8:
            raise ValueError("DCIM_PASSWORD_MIN_LENGTH must be at least 8")
        import ipaddress
        for proxy in self.trusted_proxies:
            try:
                ipaddress.ip_network(proxy, strict=False)
            except ValueError:
                raise ValueError(f"DCIM_TRUSTED_PROXIES: not an IP or CIDR: {proxy!r}") from None
        if self.env == "prod":
            if self.secret_key in WEAK_SECRETS or len(self.secret_key.encode()) < 32:
                raise ValueError("DCIM_SECRET_KEY must be set to 32+ random bytes in prod")
            if "*" in self.cors_origins or "*" in self.trusted_hosts:
                raise ValueError("Wildcards are not allowed in DCIM_CORS_ORIGINS / DCIM_TRUSTED_HOSTS in prod")
            self.cookie_secure = True
        if self.docs_enabled is None:
            # N-6: keyed on DCIM_ENV only (the real bind address isn't known to the app when uvicorn is run
            # directly); DCIM_DOCS_ENABLED=true/false overrides
            self.docs_enabled = self.env == "dev"
        return self

    @property
    def session_cookie_name(self) -> str:
        # __Host- prefix needs Secure + Path=/ and no Domain
        return "__Host-dcim_session" if self.cookie_secure else "dcim_session"


@lru_cache
def get_settings() -> Settings:
    return Settings()
