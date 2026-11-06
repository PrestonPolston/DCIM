import re
import uuid

from starlette.middleware.base import BaseHTTPMiddleware

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)
# Swagger UI loads assets from a CDN; relax CSP only on the docs pages
DOCS_CSP = (
    "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com; "
    "frame-ancestors 'none'"
)


REQUEST_ID = re.compile(r"[A-Za-z0-9-]{1,64}")


# Security headers (AUTH_RBAC_PLAN §6) + a request id for audit events
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, hsts: bool = False, trust_request_id: bool = False, hsts_max_age: int = 86400,
                 hsts_include_subdomains: bool = False, camera_self: bool = False):
        super().__init__(app)
        self.hsts = hsts
        self.hsts_value = f"max-age={int(hsts_max_age)}" + ("; includeSubDomains" if hsts_include_subdomains else "")
        self.permissions = f"camera={'(self)' if camera_self else '()'}, microphone=(), geolocation=()"
        self.trust_request_id = trust_request_id

    async def dispatch(self, request, call_next):
        # R-7: server-generated id; a proxy-supplied one is used only when trusted and well-formed
        incoming = request.headers.get("x-request-id", "")
        ok = self.trust_request_id and REQUEST_ID.fullmatch(incoming)
        request.state.request_id = incoming if ok else uuid.uuid4().hex
        response = await call_next(request)
        h = response.headers
        if "content-security-policy" not in h:  # image responses set a stricter sandbox CSP themselves
            h["Content-Security-Policy"] = DOCS_CSP if request.url.path in ("/docs", "/redoc") else CSP
        h["X-Content-Type-Options"] = "nosniff"
        h["Referrer-Policy"] = "no-referrer"
        h["X-Frame-Options"] = "DENY"
        h["Permissions-Policy"] = self.permissions
        h.setdefault("Cache-Control", "no-store")
        h["X-Request-ID"] = request.state.request_id
        if self.hsts and request.url.scheme == "https":  # browsers ignore it over HTTP; never send it there
            h["Strict-Transport-Security"] = self.hsts_value
        return response
