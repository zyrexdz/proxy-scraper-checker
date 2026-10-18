"""Country / geolocation lookup via ip-api.com.

The free tier is rate-limited to 45 requests/minute from a single source IP.
We send batched requests (up to 100 IPs per call) and run them in parallel,
which keeps the wall-clock cost low for typical working-proxy sets (usually
< 5,000 entries after a run).

ip-api.com returns:
    {"status": "success", "country": "...", "countryCode": "...", "query": "1.2.3.4"}

Failed lookups (rate-limited, private IP, malformed) are silently dropped.
"""

from __future__ import annotations

import asyncio
from typing import Iterable

import aiohttp

_BATCH_URL = "http://ip-api.com/batch"
_FIELDS = "status,countryCode,query"
_BATCH_SIZE = 100


async def _one_batch(
    session: aiohttp.ClientSession, ips: list[str]
) -> dict[str, str]:
    try:
        async with session.post(
            _BATCH_URL,
            json=ips,
            params={"fields": _FIELDS},
            timeout=aiohttp.ClientTimeout(total=20),
        ) as resp:
            if resp.status != 200:
                return {}
            data = await resp.json()
    except (aiohttp.ClientError, asyncio.TimeoutError, Exception):
        return {}

    out: dict[str, str] = {}
    for entry in data or []:
        if isinstance(entry, dict) and entry.get("status") == "success":
            ip = entry.get("query", "")
            cc = entry.get("countryCode", "")
            if ip and cc:
                out[ip] = cc
    return out


async def lookup_countries(ips: Iterable[str], *, concurrency: int = 4) -> dict[str, str]:
    """Return a mapping ``ip -> ISO country code`` for every successfully resolved IP.

    ``concurrency`` controls how many batched requests are in flight at once —
    keep this small (4–8) to stay well below ip-api.com's rate limit.
    """
    ip_list = list(dict.fromkeys(ips))  # dedupe, preserve order
    if not ip_list:
        return {}

    chunks = [ip_list[i : i + _BATCH_SIZE] for i in range(0, len(ip_list), _BATCH_SIZE)]
    sem = asyncio.Semaphore(concurrency)
    out: dict[str, str] = {}

    async with aiohttp.ClientSession() as session:
        async def run(chunk: list[str]) -> dict[str, str]:
            async with sem:
                # Respect the per-minute cap: a small sleep between batches
                # keeps a large run from getting throttled.
                await asyncio.sleep(0.25)
                return await _one_batch(session, chunk)

        results = await asyncio.gather(*(run(c) for c in chunks))
        for r in results:
            out.update(r)
    return out
