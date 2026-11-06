from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

import app.models  # noqa: F401  (registers tables)
import app.modules.audit.listeners  # noqa: F401  (location/device-type audit events)
from app.modules.audit.router import router as audit_router
from app.modules.cabinet_profiles.router import images_router as cabinet_images_router, router as cabinet_profiles_router
from app.modules.auth.router import router as auth_router
from app.modules.device_types.catalog import router as catalog_router
from app.modules.images.router import router as images_router
from app.modules.devices.router import rack_devices_router
from app.modules.device_types.profiles import router as profiles_router
from app.modules.device_types.router import router as device_types_router
from app.modules.connections.router import router as connections_router
from app.modules.devices.router import router as devices_router
from app.modules.directory.router import router as directory_router
from app.modules.locations.router import router as locations_router
from app.modules.users.router import router as users_router
from app.security.headers import SecurityHeadersMiddleware
from app.security.logredact import install_log_redaction
from app.settings import Settings, get_settings

# Routes reachable without a session (everything else is deny-by-default)
PUBLIC_PATHS = {"/", "/health", "/version", "/auth/providers", "/auth/login",
                "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    docs = settings.docs_enabled
    app = FastAPI(
        title="DCIM API", version="0.1.0",
        docs_url="/docs" if docs else None, redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )

    # Middleware (last added runs first): headers -> hosts -> CORS. R-8: headers is outermost, so even a
    # TrustedHost 400 carries the security headers.
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=["Content-Type", "X-CSRF-Token"],
            expose_headers=["X-Total-Count", "X-Decommissioned-Count"],
        )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.hsts_enabled,
                       trust_request_id=settings.trust_request_id, hsts_max_age=settings.hsts_max_age,
                       hsts_include_subdomains=settings.hsts_include_subdomains,
                       camera_self=settings.permissions_camera_self)
    install_log_redaction()  # N-4

    # R-1: 422 bodies never echo submitted values (input/ctx dropped; secrets can't be reflected)
    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError):
        detail = [{"type": e.get("type"), "loc": list(e.get("loc", ())), "msg": e.get("msg")} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": detail})

    for router in (auth_router, users_router, audit_router, locations_router,
                   device_types_router, profiles_router, devices_router, directory_router, connections_router, catalog_router, images_router, rack_devices_router,
                   cabinet_profiles_router, cabinet_images_router):
        app.include_router(router)

    @app.get("/")
    def root():
        return {"message": "DCIM API is running"}

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/version")
    def version():
        return {"version": "0.1.0"}

    return app


app = create_app()
