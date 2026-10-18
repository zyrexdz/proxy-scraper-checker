"""Target-site ban filter.

Once a proxy passes the latency/judge check, it can still be useless if the
proxy's IP is banned on the site you actually want to reach (Cloudflare 403,
Discord rate-limit, Steam region lock, etc.). This module tests each working
proxy against an opt-in list of high-value services and drops the ones that
fail.

The check is intentionally simple — a HEAD/GET against the site root, looking
for status codes that suggest a block (403, 429, 503, 5xx-with-block-page).
For ambiguous cases (e.g., Cloudflare's JS challenge that returns 403 but is
followed by a 200), we accept the proxy; perfect filtering is not the goal
here, only removing clearly-bad ones.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable, Iterable

import aiohttp
from aiohttp_socks import ProxyConnector

from .parser import Proxy
from .protocols import Protocol
from .utils import proxy_url


@dataclass(frozen=True, slots=True)
class TargetSite:
    """A service to test working proxies against."""

    name: str
    url: str
    block_codes: frozenset[int] = frozenset({403, 429})

    def is_blocked(self, code: int) -> bool:
        return code in self.block_codes or code >= 500


# Curated set of sites that heavy proxy users actually care about.
DEFAULT_TARGETS: tuple[TargetSite, ...] = (
    TargetSite("Cloudflare", "https://cloudflare.com/"),
    TargetSite("Discord", "https://discord.com/"),
    TargetSite("Steam", "https://store.steampowered.com/"),
    TargetSite("Twitch", "https://www.twitch.tv/"),
    TargetSite("Google", "https://www.google.com/"),
    TargetSite("Netflix", "https://www.netflix.com/"),
    TargetSite("Amazon", "https://www.amazon.com/"),
    TargetSite("Instagram", "https://www.instagram.com/"),
    TargetSite("Twitter/X", "https://x.com/"),
    TargetSite("Spotify", "https://www.spotify.com/"),
    TargetSite("Riot Games", "https://www.riotgames.com/"),
    TargetSite("Epic Games", "https://www.epicgames.com/"),
    TargetSite("YouTube", "https://www.youtube.com/"),
    TargetSite("Reddit", "https://www.reddit.com/"),
    TargetSite("GitHub", "https://github.com/"),
)


def all_targets() -> tuple[TargetSite, ...]:
    return DEFAULT_TARGETS


def targets_by_names(names: Iterable[str]) -> tuple[TargetSite, ...]:
    """Resolve a list of user-provided names against the default catalog."""
    by_name = {s.name: s for s in DEFAULT_TARGETS}
    return tuple(by_name[n] for n in names if n in by_name)


async def _test_one(
    proxy_url_str: str,
    site: TargetSite,
    *,
    timeout: float,
) -> bool:
    """Return True if the proxy can reach ``site`` without being blocked."""
    try:
        connector: aiohttp.BaseConnector
        if proxy_url_str.startswith(("socks4://", "socks5://", "socks5h://")):
            connector = ProxyConnector.from_url(proxy_url_str)
        else:
            from aiohttp import TCPConnector

            connector = TCPConnector()
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(
                site.url,
                timeout=aiohttp.ClientTimeout(total=timeout, connect=min(4.0, timeout)),
                allow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            ) as resp:
                return not site.is_blocked(resp.status)
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError, Exception):
        return False


async def filter_targets(
    proxies: list[tuple[Proxy, Protocol]],
    sites: tuple[TargetSite, ...],
    *,
    concurrency: int = 100,
    timeout: float = 8.0,
    progress_cb: Callable[[int, int], None] | None = None,
) -> set[tuple[Proxy, Protocol]]:
    """Run each (proxy, protocol, site) triple in parallel and keep only the proxies that pass every site.

    Returns a set of ``(proxy, protocol)`` tuples. A proxy is rejected if it
    fails ANY site (intersection logic — "works everywhere we tested").
    """
    if not proxies or not sites:
        return set(proxies)

    total = len(proxies) * len(sites)
    sem = asyncio.Semaphore(concurrency)
    completed = 0
    fail: set[tuple[Proxy, Protocol]] = set()
    lock = asyncio.Lock()

    async def run(proxy: Proxy, protocol: Protocol, site: TargetSite) -> None:
        nonlocal completed
        async with sem:
            url = proxy_url(proxy, protocol)
            ok = await _test_one(url, site, timeout=timeout)
        async with lock:
            completed += 1
            if not ok:
                fail.add((proxy, protocol))
            if progress_cb is not None:
                progress_cb(completed, total)

    tasks = [
        asyncio.create_task(run(p, proto, site))
        for (p, proto) in proxies
        for site in sites
    ]
    await asyncio.gather(*tasks)

    return set(proxies) - fail
