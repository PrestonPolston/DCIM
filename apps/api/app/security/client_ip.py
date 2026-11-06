"""N-1: the client IP used for rate limits and audit rows.

X-Forwarded-For is ignored unless the direct peer is listed in DCIM_TRUSTED_PROXIES (IPs or CIDRs).
Then the right-most address that is not itself a trusted proxy is the client. Run uvicorn with
--no-proxy-headers (python -m app does) so uvicorn never rewrites request.client from the header.
"""
import ipaddress
from functools import lru_cache

from starlette.requests import Request

from app.settings import get_settings


@lru_cache(maxsize=32)
def _networks(spec: tuple[str, ...]):
    return tuple(ipaddress.ip_network(s, strict=False) for s in spec)


def _trusted(ip: str, nets) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in n for n in nets)


def client_ip(request: Request) -> str | None:
    peer = request.client.host if request.client else None
    nets = _networks(tuple(get_settings().trusted_proxies))
    if peer is None or not nets or not _trusted(peer, nets):
        return peer
    hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    for hop in reversed(hops):
        if not _trusted(hop, nets):
            try:
                return str(ipaddress.ip_address(hop))
            except ValueError:
                return peer  # malformed header: fall back to the proxy itself
    return peer
