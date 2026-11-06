"""Run the API: python -m app [--reload]

Binds to DCIM_BIND_HOST:DCIM_PORT and starts uvicorn with proxy headers OFF (N-1), so a client
cannot pick its own IP with X-Forwarded-For. Behind a reverse proxy, set DCIM_TRUSTED_PROXIES.
"""
import sys

import uvicorn

from app.settings import get_settings

if __name__ == "__main__":
    s = get_settings()
    uvicorn.run("app.main:app", host=s.bind_host, port=s.port, proxy_headers=False,
                reload="--reload" in sys.argv[1:])
