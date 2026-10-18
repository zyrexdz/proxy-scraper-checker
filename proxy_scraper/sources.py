"""Free public proxy sources.

This module is the project's single source of truth for *where* to scrape
proxies from. Each source is tagged with:

    - a protocol bucket (http/socks4/socks5)
    - whether it requires a custom request shape (POST, headers, cookies)
    - last-known health (success/fail counts, last_seen timestamp)

Source health is persisted to ``sources_health.json`` so that persistently
broken sources can be auto-skipped on subsequent runs.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Final

from .protocols import Protocol


@dataclass(frozen=True, slots=True)
class Source:
    """A single proxy source endpoint."""

    url: str
    protocol: Protocol
    method: str = "GET"
    headers: dict[str, str] = field(default_factory=dict)
    notes: str = ""

    @property
    def key(self) -> str:
        """Stable identifier — same URL+method+headers share a health record."""
        return f"{self.method}:{self.url}"


# ---------------------------------------------------------------------------
# Source catalog.
#
# Sources are organized by protocol bucket. Each list intentionally overlaps
# with the others so a single dead source doesn't kill a whole protocol.
#
# Adding a source? Use ``Source(url, Protocol.X)``. For sources that emit a
# pre-formatted ``protocolipport`` string (e.g. the new Proxyscrape v4 API),
# the parser handles them automatically.
# ---------------------------------------------------------------------------

_HTTP_SOURCES: Final[tuple[Source, ...]] = (
    # ----- API endpoints -----
    Source("https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000", Protocol.HTTP),
    Source("https://api.proxyscrape.com/v2/?request=displayproxies&protocol=https&timeout=10000", Protocol.HTTP),
    Source("https://api.proxyscrape.com/v2/?request=displayproxies&protocol=socks4&timeout=10000", Protocol.SOCKS4),
    Source("https://api.proxyscrape.com/v2/?request=displayproxies&protocol=socks5&timeout=10000", Protocol.SOCKS5),
    Source(
        "https://api.proxyscrape.com/v4/free-proxy-list/get"
        "?request=display_proxies&proxy_format=protocolipport&format=text&protocol=http",
        Protocol.HTTP,
        notes="proxyscrape v4 — protocol-prefixed output",
    ),
    Source(
        "https://api.proxyscrape.com/v4/free-proxy-list/get"
        "?request=display_proxies&proxy_format=protocolipport&format=text&protocol=https",
        Protocol.HTTP,
    ),
    Source(
        "https://api.proxyscrape.com/v4/free-proxy-list/get"
        "?request=display_proxies&proxy_format=protocolipport&format=text&protocol=socks4",
        Protocol.SOCKS4,
    ),
    Source(
        "https://api.proxyscrape.com/v4/free-proxy-list/get"
        "?request=display_proxies&proxy_format=protocolipport&format=text&protocol=socks5",
        Protocol.SOCKS5,
    ),
    Source("https://openproxy.space/list/http", Protocol.HTTP, notes="json output"),
    Source("https://openproxy.space/list/socks4", Protocol.SOCKS4, notes="json output"),
    Source("https://openproxy.space/list/socks5", Protocol.SOCKS5, notes="json output"),

    # ----- The big GitHub mirror list (SpeedX, mono-san, ShiftyTR, Clarketm,
    #       vakhov, zevtyardt, etc.) -----
    Source("https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt", Protocol.HTTP),
    Source("https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks4.txt", Protocol.SOCKS4),
    Source("https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt", Protocol.SOCKS5),
    Source("https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt", Protocol.HTTP),
    Source("https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/socks4.txt", Protocol.SOCKS4),
    Source("https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/socks5.txt", Protocol.SOCKS5),
    Source("https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt", Protocol.HTTP),
    Source("https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks4.txt", Protocol.SOCKS4),
    Source("https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt", Protocol.SOCKS5),
    Source("https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/https.txt", Protocol.HTTP),
    Source("https://raw.githubusercontent.com/roosterkid/openproxylist/main/HTTPS_RAW.txt", Protocol.HTTP),
    Source("https://raw.githubusercontent.com/roosterkid/openproxylist/main/SOCKS4_RAW.txt", Protocol.SOCKS4),
    Source("https://raw.githubusercontent.com/roosterkid/openproxylist/main/SOCKS5_RAW.txt", Protocol.SOCKS5),
    Source("https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt", Protocol.HTTP),
    Source("https://raw.githubusercontent.com/clarketm/proxy-list/master/proxies-socks4.txt", Protocol.SOCKS4),
    Source("https://raw.githubusercontent.com/clarketm/proxy-list/master/proxies-socks5.txt", Protocol.SOCKS5),
    Source("https://raw.githubusercontent.com/vakhov/fresh-proxy-list/master/http.txt", Protocol.HTTP),
    Source("https://raw.githubusercontent.com/vakhov/fresh-proxy-list/master/https.txt", Protocol.HTTP),
    Source("https://raw.githubusercontent.com/vakhov/fresh-proxy-list/master/socks4.txt", Protocol.SOCKS4),
    Source("https://raw.githubusercontent.com/vakhov/fresh-proxy-list/master/socks5.txt", Protocol.SOCKS5),
    Source("https://raw.githubusercontent.com/zevtyardt/proxy-list/main/http.txt", Protocol.HTTP),
    Source("https://raw.githubusercontent.com/zevtyardt/proxy-list/main/socks4.txt", Protocol.SOCKS4),
    Source("https://raw.githubusercontent.com/zevtyardt/proxy-list/main/socks5.txt", Protocol.SOCKS5),
    Source("https://raw.githubusercontent.com/prxchk/proxy-list/main/http.txt", Protocol.HTTP),
    Source("https://raw.githubusercontent.com/ALIILAPRO/Proxy/main/http.txt", Protocol.HTTP),
    Source("https://raw.githubusercontent.com/ALIILAPRO/Proxy/main/socks4.txt", Protocol.SOCKS4),
    Source("https://raw.githubusercontent.com/ALIILAPRO/Proxy/main/socks5.txt", Protocol.SOCKS5),
    Source("https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt", Protocol.SOCKS5),
    Source("https://raw.githubusercontent.com/sunny9577/proxy-scraper/master/proxies.txt", Protocol.HTTP),
    Source("https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-http.txt", Protocol.HTTP),
    Source("https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-https.txt", Protocol.HTTP),
    Source("https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-socks4.txt", Protocol.SOCKS4),
    Source("https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-socks5.txt", Protocol.SOCKS5),
    Source("https://raw.githubusercontent.com/proxy4parsing/proxy-list/main/http.txt", Protocol.HTTP),
    Source("https://api.openproxylist.xyz/http.txt", Protocol.HTTP),
    Source("https://api.openproxylist.xyz/https.txt", Protocol.HTTP),
    Source("https://api.openproxylist.xyz/socks4.txt", Protocol.SOCKS4),
    Source("https://api.openproxylist.xyz/socks5.txt", Protocol.SOCKS5),
    Source("https://proxylist.geonode.com/api/proxy-list?limit=500&page=1&sort_by=lastChecked&sort_type=desc", Protocol.HTTP, notes="geonode json"),
    Source("https://proxylist.geonode.com/api/proxy-list?limit=500&page=2&sort_by=lastChecked&sort_type=desc", Protocol.HTTP),
    Source("https://proxylist.geonode.com/api/proxy-list?limit=500&page=3&sort_by=lastChecked&sort_type=desc", Protocol.HTTP),
    Source("https://imtaqin.id/api/proxies", Protocol.HTTP),
    Source("http://pubproxy.com/api/proxy?limit=20&format=txt", Protocol.HTTP),

    # ----- Newly added (research Oct 2026) -----
    # mmpx12/proxy-list — hourly, all 4 protocols
    Source("https://raw.githubusercontent.com/mmpx12/proxy-list/master/http.txt", Protocol.HTTP, notes="mmpx12"),
    Source("https://raw.githubusercontent.com/mmpx12/proxy-list/master/https.txt", Protocol.HTTP),
    Source("https://raw.githubusercontent.com/mmpx12/proxy-list/master/socks4.txt", Protocol.SOCKS4),
    Source("https://raw.githubusercontent.com/mmpx12/proxy-list/master/socks5.txt", Protocol.SOCKS5),
    # iplocate/free-proxy-list — cleanest plain-text format
    Source("https://raw.githubusercontent.com/iplocate/free-proxy-list/main/protocols/http.txt", Protocol.HTTP, notes="iplocate"),
    Source("https://raw.githubusercontent.com/iplocate/free-proxy-list/main/protocols/https.txt", Protocol.HTTP),
    Source("https://raw.githubusercontent.com/iplocate/free-proxy-list/main/protocols/socks4.txt", Protocol.SOCKS4),
    Source("https://raw.githubusercontent.com/iplocate/free-proxy-list/main/protocols/socks5.txt", Protocol.SOCKS5),
    # hproxy-com/free-proxy-list
    Source("https://raw.githubusercontent.com/hproxy-com/free-proxy-list/main/http.txt", Protocol.HTTP),
    Source("https://raw.githubusercontent.com/hproxy-com/free-proxy-list/main/https.txt", Protocol.HTTP),
    Source("https://raw.githubusercontent.com/hproxy-com/free-proxy-list/main/socks4.txt", Protocol.SOCKS4),
    Source("https://raw.githubusercontent.com/hproxy-com/free-proxy-list/main/socks5.txt", Protocol.SOCKS5),
    # SoliSpirit/proxy-list
    Source("https://raw.githubusercontent.com/SoliSpirit/proxy-list/master/http.txt", Protocol.HTTP),
    Source("https://raw.githubusercontent.com/SoliSpirit/proxy-list/master/https.txt", Protocol.HTTP),
    Source("https://raw.githubusercontent.com/SoliSpirit/proxy-list/master/socks4.txt", Protocol.SOCKS4),
    Source("https://raw.githubusercontent.com/SoliSpirit/proxy-list/master/socks5.txt", Protocol.SOCKS5),
    # databay-labs/free-proxy-list — 5 min refresh
    Source("https://raw.githubusercontent.com/databay-labs/free-proxy-list/master/http.txt", Protocol.HTTP, notes="databay-labs"),
    Source("https://raw.githubusercontent.com/databay-labs/free-proxy-list/master/https.txt", Protocol.HTTP),
    Source("https://raw.githubusercontent.com/databay-labs/free-proxy-list/master/socks4.txt", Protocol.SOCKS4),
    Source("https://raw.githubusercontent.com/databay-labs/free-proxy-list/master/socks5.txt", Protocol.SOCKS5),
    # ProxyScrape/free-proxy-list
    Source("https://raw.githubusercontent.com/ProxyScrape/free-proxy-list/main/proxies/protocols/http/data.txt", Protocol.HTTP),
    Source("https://raw.githubusercontent.com/ProxyScrape/free-proxy-list/main/proxies/protocols/https/data.txt", Protocol.HTTP),
    Source("https://raw.githubusercontent.com/ProxyScrape/free-proxy-list/main/proxies/protocols/socks4/data.txt", Protocol.SOCKS4),
    Source("https://raw.githubusercontent.com/ProxyScrape/free-proxy-list/main/proxies/protocols/socks5/data.txt", Protocol.SOCKS5),
    # proxygenerator1/ProxyGenerator — Stable tier
    Source("https://raw.githubusercontent.com/proxygenerator1/ProxyGenerator/main/Stable/http.txt", Protocol.HTTP, notes="proxygenerator Stable"),
    Source("https://raw.githubusercontent.com/proxygenerator1/ProxyGenerator/main/Stable/https.txt", Protocol.HTTP),
    Source("https://raw.githubusercontent.com/proxygenerator1/ProxyGenerator/main/Stable/socks4.txt", Protocol.SOCKS4),
    Source("https://raw.githubusercontent.com/proxygenerator1/ProxyGenerator/main/Stable/socks5.txt", Protocol.SOCKS5),
    # vmheaven/VMHeaven.io-Free-Proxy-List — AWS-filtered
    Source("https://raw.githubusercontent.com/vmheaven/VMHeaven.io-Free-Proxy-List/main/http.txt", Protocol.HTTP, notes="vmheaven, AWS-filtered"),
    Source("https://raw.githubusercontent.com/vmheaven/VMHeaven.io-Free-Proxy-List/main/https.txt", Protocol.HTTP),
    Source("https://raw.githubusercontent.com/vmheaven/VMHeaven.io-Free-Proxy-List/main/socks4.txt", Protocol.SOCKS4),
    Source("https://raw.githubusercontent.com/vmheaven/VMHeaven.io-Free-Proxy-List/main/socks5.txt", Protocol.SOCKS5),
    # xyzs996/free-proxy-health-list — health-rechecked every 30 min
    Source("https://raw.githubusercontent.com/xyzs996/free-proxy-health-list/main/http.txt", Protocol.HTTP, notes="xyzs996, health-rechecked"),
    Source("https://raw.githubusercontent.com/xyzs996/free-proxy-health-list/main/https.txt", Protocol.HTTP),
    Source("https://raw.githubusercontent.com/xyzs996/free-proxy-health-list/main/socks4.txt", Protocol.SOCKS4),
    Source("https://raw.githubusercontent.com/xyzs996/free-proxy-health-list/main/socks5.txt", Protocol.SOCKS5),
    # elliottophellia/proxylist — nested path, per-country cuts
    Source("https://raw.githubusercontent.com/elliottophellia/proxylist/main/results/http/global/http_checked.txt", Protocol.HTTP, notes="elliottophellia"),
    Source("https://raw.githubusercontent.com/elliottophellia/proxylist/main/results/https/global/https_checked.txt", Protocol.HTTP),
    Source("https://raw.githubusercontent.com/elliottophellia/proxylist/main/results/socks4/global/socks4_checked.txt", Protocol.SOCKS4),
    Source("https://raw.githubusercontent.com/elliottophellia/proxylist/main/results/socks5/global/socks5_checked.txt", Protocol.SOCKS5),
    # ClearProxy/checked-proxy-list — tested against popular sites
    Source("https://raw.githubusercontent.com/ClearProxy/checked-proxy-list/main/http.txt", Protocol.HTTP, notes="ClearProxy, site-tested"),
    Source("https://raw.githubusercontent.com/ClearProxy/checked-proxy-list/main/socks4.txt", Protocol.SOCKS4),
    Source("https://raw.githubusercontent.com/ClearProxy/checked-proxy-list/main/socks5.txt", Protocol.SOCKS5),
    # openproxyhub/proxy-exports
    Source("https://raw.githubusercontent.com/openproxyhub/proxy-exports/main/http.txt", Protocol.HTTP, notes="openproxyhub"),
    Source("https://raw.githubusercontent.com/openproxyhub/proxy-exports/main/socks4.txt", Protocol.SOCKS4),
    Source("https://raw.githubusercontent.com/openproxyhub/proxy-exports/main/socks5.txt", Protocol.SOCKS5),
    # rix4uni/fresh-proxy-list — combined file
    Source("https://raw.githubusercontent.com/rix4uni/fresh-proxy-list/main/proxylist.txt", Protocol.HTTP, notes="rix4uni, combined"),
    # Thordata/awesome-free-proxy-list
    Source("https://raw.githubusercontent.com/Thordata/awesome-free-proxy-list/main/http.txt", Protocol.HTTP, notes="Thordata, metadata-rich"),
    Source("https://raw.githubusercontent.com/Thordata/awesome-free-proxy-list/main/socks4.txt", Protocol.SOCKS4),
    Source("https://raw.githubusercontent.com/Thordata/awesome-free-proxy-list/main/socks5.txt", Protocol.SOCKS5),
    # saisuiu/Lionkings-Http-Proxys-Proxies
    Source("https://raw.githubusercontent.com/saisuiu/Lionkings-Http-Proxys-Proxies/main/free.txt", Protocol.HTTP, notes="saisuiu, HTTP-focused"),
    # proxifly (raw + jsdelivr CDN mirror)
    Source("https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/http/data.txt", Protocol.HTTP, notes="proxifly, 75k+ proxies"),
    Source("https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/socks4/data.txt", Protocol.SOCKS4),
    Source("https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/socks5/data.txt", Protocol.SOCKS5),
    Source("https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/https/data.txt", Protocol.HTTP),
    Source("https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/http/data.txt", Protocol.HTTP),
    Source("https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/socks4/data.txt", Protocol.SOCKS4),
    Source("https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/socks5/data.txt", Protocol.SOCKS5),
    Source("https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/https/data.txt", Protocol.HTTP),

    Source("https://raw.githubusercontent.com/VPSLabCloud/VPSLab-Free-Proxy-List/main/http_all.txt", Protocol.HTTP),
    Source("https://raw.githubusercontent.com/VPSLabCloud/VPSLab-Free-Proxy-List/main/socks4_all.txt", Protocol.SOCKS4),
    Source("https://raw.githubusercontent.com/VPSLabCloud/VPSLab-Free-Proxy-List/main/socks5_all.txt", Protocol.SOCKS5),
    Source("https://raw.githubusercontent.com/adasd223/http-proxy-list-2026/main/http.txt", Protocol.HTTP),
    Source("https://raw.githubusercontent.com/adasd223/http-proxy-list-2026/main/socks4.txt", Protocol.SOCKS4),
    Source("https://raw.githubusercontent.com/adasd223/http-proxy-list-2026/main/socks5.txt", Protocol.SOCKS5),
    Source("https://raw.githubusercontent.com/dpangestuw/Free-Proxy/main/http_proxies.txt", Protocol.HTTP),
    Source("https://raw.githubusercontent.com/dpangestuw/Free-Proxy/main/socks5_proxies.txt", Protocol.SOCKS5),
    Source("https://raw.githubusercontent.com/r00tee/Proxy-List/main/Http.txt", Protocol.HTTP),
    Source("https://raw.githubusercontent.com/r00tee/Proxy-List/main/Socks5.txt", Protocol.SOCKS5),
    Source("https://raw.githubusercontent.com/r00tee/Proxy-List/main/Socks4.txt", Protocol.SOCKS4),
    Source("https://raw.githubusercontent.com/wiki/gfpcom/free-proxy-list/lists/http.txt", Protocol.HTTP),
    Source("https://raw.githubusercontent.com/wiki/gfpcom/free-proxy-list/lists/socks5.txt", Protocol.SOCKS5),
    Source("https://freshfreeproxylist.wordpress.com/", Protocol.HTTP),
    Source("https://www.my-proxy.com/free-proxy-list.html", Protocol.HTTP),
    Source("https://www.my-proxy.com/free-socks-4-proxy.html", Protocol.SOCKS4),
    Source("https://www.my-proxy.com/free-socks-5-proxy.html", Protocol.SOCKS5),
    Source("https://free-proxy-list.net/", Protocol.HTTP),
    Source("https://www.sslproxies.org/", Protocol.HTTP),
    Source("https://us-proxy.org/", Protocol.HTTP),
    Source("https://www.socks-proxy.net/", Protocol.SOCKS4),
    Source("https://webanetlabs.net/publ/24", Protocol.HTTP),
    Source("https://sockslist.us/Api?request=display&country=all&level=all&token=free", Protocol.SOCKS5),
    Source("https://proxyhub.me/en/all-socks-proxy-list.html", Protocol.SOCKS5),
    Source("https://papaproxy.net/ru/socks.php", Protocol.SOCKS5),
    Source("https://papaproxy.net/ru/socks5.php", Protocol.SOCKS5),
    Source("https://cyber-gateway.net/get-proxy/free-proxy/56-free-socks-proxy", Protocol.SOCKS5),
    Source("https://list.proxylistplus.com/Socks-List-1", Protocol.SOCKS4),
    Source("https://list.proxylistplus.com/HTTP-List-1", Protocol.HTTP),
    Source("https://api.nameless.com.np/api/proxy", Protocol.HTTP, notes="community-hosted API"),
    Source("https://www.proxyscan.io/api/proxy?format=txt&type=http", Protocol.HTTP),
    Source("https://www.proxyscan.io/api/proxy?format=txt&type=socks4", Protocol.SOCKS4),
    Source("https://www.proxyscan.io/api/proxy?format=txt&type=socks5", Protocol.SOCKS5),

    # ----- Country-specific (opt-in via --extra-sources) -----
    Source("https://proxy5.net/free-proxy/iran", Protocol.HTTP, notes="country-specific: Iran"),
    Source("https://proxy5.net/free-proxy/china", Protocol.HTTP, notes="country-specific: China"),
    Source("https://fineproxy.org/free-proxies/asia/china/", Protocol.HTTP, notes="country-specific: China, 15-min refresh"),
    Source("https://saisuiu/Lionkings-Http-Proxys-Proxies/main/cnfree.txt", Protocol.HTTP, notes="country-specific: China"),
)

# External HTML scrapers — disabled by default because they require a parser
# tailored to each site. Left here as a hook for v3.1.
_EXTRA_SOURCES: Final[tuple[Source, ...]] = (
    Source("https://hidemy.name/en/proxy-list/", Protocol.HTTP),
    Source("https://spys.one/en/free-proxy-list/", Protocol.HTTP),
    Source("https://www.proxynova.com/proxy-list/", Protocol.HTTP),
    Source("https://hide.mn/en/proxy-list/", Protocol.HTTP, notes="static HTML, paginated, ~16k entries"),
    Source("https://free.geonix.com/en/", Protocol.HTTP, notes="static HTML, country/anonymity filters"),
    Source("https://www.live-socks.net/", Protocol.SOCKS4, notes="socks specialists, dated archive URLs"),
    Source("https://www.live-socks.net/", Protocol.SOCKS5),
    Source("https://advanced.name/freeproxy", Protocol.HTTP, notes="~706 live proxies"),
)

# All sources combined (extra ones are opt-in).
ALL_SOURCES: Final[tuple[Source, ...]] = _HTTP_SOURCES + _EXTRA_SOURCES


def sources_for(protocols: Iterable[Protocol], *, include_extra: bool = False) -> tuple[Source, ...]:
    """Return the subset of sources that match any of the given protocols."""
    wanted = set(protocols)
    pool = ALL_SOURCES if include_extra else _HTTP_SOURCES
    return tuple(s for s in pool if s.protocol in wanted)


def sources_by_protocol(
    protocols: Iterable[Protocol], *, include_extra: bool = False
) -> dict[Protocol, list[Source]]:
    bucket: dict[Protocol, list[Source]] = {p: [] for p in protocols}
    for src in sources_for(protocols, include_extra=include_extra):
        bucket[src.protocol].append(src)
    return bucket


# ---------------------------------------------------------------------------
# Source health tracking.
# ---------------------------------------------------------------------------


@dataclass
class SourceHealth:
    """Rollup of success/failure history for a single source."""

    key: str
    successes: int = 0
    failures: int = 0
    last_success_ts: float = 0.0
    last_failure_ts: float = 0.0
    last_seen_count: int = 0
    consecutive_failures: int = 0

    @property
    def success_rate(self) -> float:
        total = self.successes + self.failures
        return self.successes / total if total else 0.0

    @property
    def is_stale(self) -> bool:
        # Auto-skip after 5 consecutive failures.
        return self.consecutive_failures >= 5

    def record_success(self, *, count: int) -> None:
        self.successes += 1
        self.last_success_ts = time.time()
        self.last_seen_count = count
        self.consecutive_failures = 0

    def record_failure(self) -> None:
        self.failures += 1
        self.last_failure_ts = time.time()
        self.consecutive_failures += 1

    def as_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> SourceHealth:
        return cls(**data)


class SourceHealthBook:
    """Persistent ledger of per-source health.

    Backed by a JSON file on disk. Use ``record()`` to update, ``is_stale()``
    to check, and ``save()`` to persist after a run.
    """

    DEFAULT_PATH = Path("sources_health.json")

    def __init__(self, path: Path | None = None, *, auto_load: bool = True) -> None:
        self.path = Path(path) if path else self.DEFAULT_PATH
        self._records: dict[str, SourceHealth] = {}
        if auto_load and self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                for key, entry in data.items():
                    self._records[key] = SourceHealth.from_dict(entry)
            except (json.JSONDecodeError, OSError, TypeError):
                # Corrupt or unreadable file — start fresh.
                self._records = {}

    def get(self, source: Source) -> SourceHealth:
        if source.key not in self._records:
            self._records[source.key] = SourceHealth(key=source.key)
        return self._records[source.key]

    def record_success(self, source: Source, *, count: int) -> None:
        self.get(source).record_success(count=count)

    def record_failure(self, source: Source) -> None:
        self.get(source).record_failure()

    def is_stale(self, source: Source) -> bool:
        return self.get(source).is_stale

    def reset_consecutive(self, source: Source) -> None:
        """Clear the consecutive-failure counter — useful after a manual refresh."""
        self.get(source).consecutive_failures = 0

    def save(self) -> None:
        try:
            payload = {k: v.as_dict() for k, v in self._records.items()}
            self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:
            pass

    def snapshot(self) -> dict[str, dict]:
        """Return a JSON-serializable summary for the UI / debug."""
        return {k: v.as_dict() for k, v in self._records.items()}
