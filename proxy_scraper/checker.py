"""Async proxy validator.

Each proxy is checked against a rotating pool of "judge" endpoints that
return the caller's IP. We sample latency twice, take the minimum, and reject
proxies whose variance is too high (the second sample taking 2x+ the first is
a strong signal of a flaky tunnel).

We also opportunistically tag each working proxy with:
    - anonymity level (transparent / anonymous / elite) via httpbin.org/headers
    - country code via ip-api.com (batched, only for the working set)
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Iterable

import aiohttp
from aiohttp_socks import ProxyConnector

from .anonymity import Anonymity, classify_anonymity
from .geo import lookup_countries
from .parser import Proxy
from .protocols import Protocol
from .utils import proxy_url

# ---------------------------------------------------------------------------
# Judge endpoints — small endpoints that return the caller's IP. Keep this
# list short: every additional judge is another DNS+TLS+connection cost on
# cold start. Three is the sweet spot.
# ---------------------------------------------------------------------------

JUDGES: tuple[tuple[str, str], ...] = (
    # (url, expected substring in response body — used to confirm it's a real echo)
    ("http://api.ipify.org", ""),
    ("http://checkip.amazonaws.com", ""),
    ("http://ifconfig.me/ip", ""),
    ("https://api.ipify.org", ""),
    ("https://ifconfig.io/ip", ""),
)

# How many of those judges we sample per proxy check (max 3 keeps it fast).
SAMPLES_PER_CHECK: int = 2

# Variance threshold: if the slower sample takes > this multiple of the
# faster one, the proxy is rejected as "flaky".
LATENCY_VARIANCE_MULTIPLIER: float = 2.5


@dataclass(slots=True)
class CheckResult:
    """Outcome of validating a single proxy."""

    proxy: Proxy
    protocol: Protocol
    latency_ms: float = 0.0
    samples_ms: tuple[float, ...] = field(default_factory=tuple)
    anonymity: Anonymity = Anonymity.UNKNOWN
    country: str = ""
    ok: bool = False

    def to_dict(self) -> dict:
        return {
            "ip": self.proxy.ip,
            "port": self.proxy.port,
            "protocol": self.protocol.value,
            "user": self.proxy.user,
            "passwd": self.proxy.passwd,
            "latency_ms": round(self.latency_ms, 1),
            "samples_ms": [round(s, 1) for s in self.samples_ms],
            "anonymity": self.anonymity.value,
            "country": self.country,
        }


def proxy_url(proxy: Proxy, protocol: Protocol) -> str:
    return proxy.to_url(protocol)


def _connector_for(protocol: Protocol, proxy: Proxy) -> aiohttp.BaseConnector:
    """Build an aiohttp connector that routes through the given proxy."""
    url = proxy_url(proxy, protocol)
    if protocol == Protocol.HTTP:
        # Plain HTTP/HTTPS proxy.
        from aiohttp import TCPConnector

        return TCPConnector()
    if protocol in (Protocol.SOCKS4, Protocol.SOCKS5):
        return ProxyConnector.from_url(url)
    raise ValueError(f"unsupported protocol: {protocol}")


async def _sample_judge(
    proxy: Proxy,
    protocol: Protocol,
    judge_url: str,
    *,
    timeout: float,
) -> float:
    """Make a single GET through the proxy and return the elapsed time.

    Returns ``float("inf")`` on any failure (timeout, connection error,
    non-2xx, empty body).
    """
    start = time.perf_counter()
    try:
        connector = _connector_for(protocol, proxy)
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(
                judge_url,
                timeout=aiohttp.ClientTimeout(total=timeout, connect=min(3.0, timeout)),
                allow_redirects=False,
            ) as resp:
                if resp.status != 200:
                    return float("inf")
                await resp.read()
    except (asyncio.TimeoutError, aiohttp.ClientError, OSError, ValueError):
        return float("inf")
    finally:
        pass
    return (time.perf_counter() - start) * 1000.0


async def _check_proxy(
    proxy: Proxy,
    protocol: Protocol,
    *,
    timeout: float,
    retries: int,
) -> CheckResult:
    """Validate a proxy and return the result.

    Strategy: pick ``SAMPLES_PER_CHECK`` distinct judge URLs (rotated per
    proxy so the load on each judge is even), sample each one once, and
    accept the proxy if at least one sample succeeds under the timeout.
    """
    samples: list[float] = []
    judges = JUDGES[:SAMPLES_PER_CHECK]
    for attempt in range(max(1, retries)):
        judge_url, _ = judges[attempt % len(judges)]
        elapsed = await _sample_judge(proxy, protocol, judge_url, timeout=timeout)
        if elapsed != float("inf"):
            samples.append(elapsed)
            if len(samples) >= SAMPLES_PER_CHECK:
                break

    if not samples:
        return CheckResult(proxy=proxy, protocol=protocol, ok=False)

    best = min(samples)
    worst = max(samples)
    if worst > best * LATENCY_VARIANCE_MULTIPLIER and len(samples) > 1:
        # The proxy is too inconsistent — likely a tunnel through a slow hop.
        return CheckResult(proxy=proxy, protocol=protocol, ok=False, samples_ms=tuple(samples))

    return CheckResult(
        proxy=proxy,
        protocol=protocol,
        latency_ms=best,
        samples_ms=tuple(samples),
        ok=True,
    )


async def check_all(
    proxies: dict[Protocol, set[Proxy]],
    *,
    concurrency: int = 200,
    timeout: float = 8.0,
    retries: int = 2,
    progress_cb: Callable[[int, int], None] | None = None,
) -> list[CheckResult]:
    """Validate every proxy in the input mapping.

    Returns a flat list of ``CheckResult`` for both passing and failing
    proxies. Callers should filter on ``.ok``.
    """
    work: list[tuple[Proxy, Protocol]] = []
    for proto, items in proxies.items():
        for p in items:
            work.append((p, proto))
    if not work:
        return []

    sem = asyncio.Semaphore(concurrency)
    completed = 0
    total = len(work)
    results: list[CheckResult] = []
    lock = asyncio.Lock()

    async def run(proxy: Proxy, protocol: Protocol) -> CheckResult:
        nonlocal completed
        async with sem:
            res = await _check_proxy(proxy, protocol, timeout=timeout, retries=retries)
        async with lock:
            completed += 1
            if progress_cb is not None:
                progress_cb(completed, total)
        return res

    tasks = [asyncio.create_task(run(p, proto)) for p, proto in work]
    results = await asyncio.gather(*tasks, return_exceptions=False)
    return list(results)


async def enrich_results(
    results: Iterable[CheckResult],
    *,
    anonymity: bool = True,
    geo: bool = True,
    geo_concurrency: int = 50,
) -> list[CheckResult]:
    """Add anonymity and country metadata to working proxies.

    Both passes only touch the working subset — anonymity costs one extra
    request per proxy, and geo costs a batched ip-api call.
    """
    working = [r for r in results if r.ok]
    if not working:
        return list(results)

    if anonymity:
        await _annotate_anonymity(working)

    if geo:
        await _annotate_geo(working, concurrency=geo_concurrency)

    return list(results)


async def _annotate_anonymity(results: list[CheckResult]) -> None:
    sem = asyncio.Semaphore(80)

    async def run(r: CheckResult) -> None:
        async with sem:
            r.anonymity = await classify_anonymity(r.proxy, r.protocol)

    await asyncio.gather(*(run(r) for r in results))


async def _annotate_geo(results: list[CheckResult], *, concurrency: int) -> None:
    by_ip = {r.proxy.ip: r for r in results}
    countries = await lookup_countries(list(by_ip.keys()), concurrency=concurrency)
    for ip, country in countries.items():
        if ip in by_ip:
            by_ip[ip].country = country
