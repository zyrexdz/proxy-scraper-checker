"""Async source scraper.

Pulls a configured set of sources concurrently, parses each payload, and
returns the deduplicated union. Per-source success and failure counts are
recorded into a ``SourceHealthBook`` so chronically dead sources can be
auto-skipped on subsequent runs.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Iterable

import aiohttp

from .parser import Proxy, parse
from .protocols import Protocol
from .sources import Source, SourceHealthBook

# Realistic User-Agents. Picked from the latest stable browser versions
# known at release time; rotated to reduce per-source fingerprinting.
_USER_AGENTS: tuple[str, ...] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
)


def _pick_headers(source: Source) -> dict[str, str]:
    """Build request headers, fanning the User-Agent to reduce per-source fingerprinting."""
    base = {"User-Agent": random.choice(_USER_AGENTS)}
    base.update(source.headers)
    return base


async def _fetch_one(
    session: aiohttp.ClientSession,
    source: Source,
    *,
    timeout: float,
    health: SourceHealthBook,
) -> set[Proxy]:
    if health.is_stale(source):
        return set()
    try:
        async with session.get(
            source.url,
            headers=_pick_headers(source),
            timeout=aiohttp.ClientTimeout(total=timeout),
            allow_redirects=True,
        ) as resp:
            if resp.status != 200:
                health.record_failure(source)
                return set()
            text = await resp.text(errors="ignore")
    except (asyncio.TimeoutError, aiohttp.ClientError, Exception):
        # All error classes — failures are recorded but never raised, so
        # one bad source never blocks the rest of the run.
        health.record_failure(source)
        return set()

    if not text:
        health.record_failure(source)
        return set()

    parsed = parse(text, expected=source.protocol)
    if parsed:
        health.record_success(source, count=len(parsed))
    else:
        # Got a response but no proxies — counts as a "soft" failure for
        # health purposes (likely the source changed format).
        health.record_failure(source)
    return parsed


async def scrape(
    sources: Iterable[Source],
    *,
    concurrency: int = 50,
    timeout: float = 15.0,
    health: SourceHealthBook | None = None,
) -> dict[Protocol, set[Proxy]]:
    """Fetch and parse all sources in parallel.

    Returns a mapping of protocol -> set of proxies (already deduplicated
    across all sources for that protocol).
    """
    sources = tuple(sources)
    if not sources:
        return {}

    health = health or SourceHealthBook(auto_load=False)
    out: dict[Protocol, set[Proxy]] = {}

    connector = aiohttp.TCPConnector(limit=concurrency, ttl_dns_cache=300, ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        sem = asyncio.Semaphore(concurrency)

        async def run(src: Source) -> set[Proxy]:
            async with sem:
                return await _fetch_one(session, src, timeout=timeout, health=health)

        tasks = [asyncio.create_task(run(s)) for s in sources]
        results = await asyncio.gather(*tasks, return_exceptions=False)

        for src, proxies in zip(sources, results):
            out.setdefault(src.protocol, set()).update(proxies)

    return out
