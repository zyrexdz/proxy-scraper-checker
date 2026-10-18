"""Anonymity classification.

A proxy's anonymity level describes how much information it leaks about
the originating client:

    - transparent: the proxy forwards identifying headers (``X-Forwarded-For``,
      ``Via``, ``X-Real-IP``) containing the real client IP. Useless for
      privacy.
    - anonymous: the proxy strips the real client IP but advertises itself
      as a proxy (e.g., via ``Via`` or ``Proxy-Connection`` headers).
    - elite: the proxy strips the real client IP AND adds no proxy-revealing
      headers. Indistinguishable from a direct connection at the HTTP layer.

We classify by hitting ``httpbin.org/headers`` through the proxy and inspecting
the headers it returns. A direct baseline hit tells us our real client IP,
which we then search for in the proxied response.
"""

from __future__ import annotations

import asyncio
from enum import Enum

import aiohttp
from aiohttp_socks import ProxyConnector

from .parser import Proxy
from .protocols import Protocol
from .utils import proxy_url

_HEADER_PROBE_URL = "http://httpbin.org/headers"

# Headers that, when present in the proxied response, indicate that the
# proxy is forwarding or revealing the original client.
_LEAKING_HEADERS = (
    "x-forwarded-for",
    "x-real-ip",
    "x-client-ip",
    "client-ip",
    "forwarded",
    "true-client-ip",
    "cf-connecting-ip",
)

# Headers that, when present, indicate the proxy is announcing itself
# (without leaking the client).
_PROXY_REVEALING_HEADERS = (
    "via",
    "proxy-connection",
    "x-proxy-id",
    "x-proxy",
    "x-bluecoat-via",
)


class Anonymity(str, Enum):
    """Proxy anonymity tier."""

    UNKNOWN = "unknown"
    TRANSPARENT = "transparent"
    ANONYMOUS = "anonymous"
    ELITE = "elite"

    @property
    def rank(self) -> int:
        """Higher is better. Useful for sorting and filtering."""
        return {
            Anonymity.UNKNOWN: 0,
            Anonymity.TRANSPARENT: 1,
            Anonymity.ANONYMOUS: 2,
            Anonymity.ELITE: 3,
        }[self]


async def _direct_own_ip() -> str:
    """Return our real outbound IP. Best-effort; empty on failure."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("http://api.ipify.org", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    return (await resp.text()).strip()
    except (aiohttp.ClientError, asyncio.TimeoutError, Exception):
        pass
    return ""


async def _headers_via_proxy(proxy: Proxy, protocol: Protocol) -> dict[str, str] | None:
    try:
        connector: aiohttp.BaseConnector
        if protocol == Protocol.HTTP:
            from aiohttp import TCPConnector

            connector = TCPConnector()
        else:
            connector = ProxyConnector.from_url(_proxy_url(proxy, protocol))
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(
                _HEADER_PROBE_URL,
                timeout=aiohttp.ClientTimeout(total=8.0, connect=4.0),
                allow_redirects=False,
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                return {k.lower(): str(v) for k, v in (data.get("headers") or {}).items()}
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError, Exception):
        return None


async def classify_anonymity(proxy: Proxy, protocol: Protocol) -> Anonymity:
    """Return the anonymity tier of the given proxy."""
    headers = await _headers_via_proxy(proxy, protocol)
    if not headers:
        return Anonymity.UNKNOWN

    # 1. Does the proxy forward our real IP?
    own_ip = await _direct_own_ip()
    if own_ip:
        for h in _LEAKING_HEADERS:
            value = headers.get(h, "")
            if own_ip in value:
                return Anonymity.TRANSPARENT

    # 2. Does the proxy forward *any* X-Forwarded-For (even with an unrelated IP)?
    # Treat that as transparent too — most anonymity-sensitive use cases reject
    # the entire X-Forwarded-For family.
    for h in _LEAKING_HEADERS:
        if h in headers:
            return Anonymity.TRANSPARENT

    # 3. Does the proxy announce itself via Via/Proxy-Connection/etc?
    for h in _PROXY_REVEALING_HEADERS:
        if h in headers:
            return Anonymity.ANONYMOUS

    return Anonymity.ELITE
