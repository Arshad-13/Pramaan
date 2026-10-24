"""Who is really calling? (Spec Section 8.4)

The browser talks to FastAPI directly, so the peer address IS the client. `X-Forwarded-For` is
only believed when the immediate peer is a proxy listed in TRUSTED_PROXY_IPS (empty by default);
otherwise anyone could write any address in that header and dodge rate limits and alerts.
"""

from __future__ import annotations

import ipaddress

from fastapi import Request

from app.config import get_settings


def _trusted() -> set[str]:
    return {p.strip() for p in get_settings().trusted_proxy_ips.split(",") if p.strip()}


def _clean(value: str) -> str | None:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def client_ip(request: Request) -> str | None:
    peer = request.client.host if request.client else None
    trusted = _trusted()
    if peer is None or peer not in trusted:
        return peer
    # Walk the chain from the nearest hop outwards; the first address that is not one of our own
    # proxies is the client. Malformed entries end the walk (fall back to the peer).
    for hop in reversed(request.headers.get("x-forwarded-for", "").split(",")):
        address = _clean(hop)
        if address is None:
            return peer
        if address not in trusted:
            return address
    return peer
