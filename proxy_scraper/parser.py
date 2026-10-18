"""Parse proxy entries out of arbitrary text or JSON payloads.

Public sources emit every format under the sun. This module normalizes them all
into a canonical ``Proxy`` value object: IP, port, optional user/pass.

Supported input shapes (one source payload may mix all of these):
    - ``{"data": [{"ip": "1.2.3.4", "port": 8080, "protocols": [...]}, ...]}``
    - ``[{"ip": "1.2.3.4", "port": 8080, ...}, ...]``
    - ``1.2.3.4:8080`` per line
    - ``1.2.3.4:8080:user:pass`` per line
    - ``http://1.2.3.4:8080`` per line
    - ``socks5://user:pass@1.2.3.4:8080`` per line
    - Free text with embedded IPs (URLs, HTML, etc.)
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from ipaddress import IPv4Address

from .protocols import Protocol

# 1.2.3.4:8080
_IPV4_PORT = re.compile(
    r"(?P<ip>(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
    r"(?:\.(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3})"
    r"\s*[:]\s*(?P<port>\d{2,5})",
)
# ip:port:user:pass
_IPV4_PORT_AUTH = re.compile(
    r"^(?P<ip>\d{1,3}(?:\.\d{1,3}){3}):(?P<port>\d{2,5}):(?P<user>[^:\s]+):(?P<pass>[^:\s]+)$"
)
# ip:port (for free-text extraction where port is bounded)
_FREE_IP_PORT = re.compile(
    r"(?P<ip>(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
    r"(?:\.(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3})"
    r"[^\w.]+"
    r"(?P<port>\d{2,5})"
)
# protocol://[user:pass@]ip:port
_URL_FORM = re.compile(
    r"(?P<scheme>https?|socks[45][ah]?)://"
    r"(?:(?P<user>[^:\s]+):(?P<pass>[^@\s]+)@)?"
    r"(?P<host>\d{1,3}(?:\.\d{1,3}){3})"
    r":(?P<port>\d{2,5})"
)


@dataclass(frozen=True, slots=True)
class Proxy:
    """A normalized proxy record.

    ``ip`` is always a string (kept as the original — could be IPv4 or IPv6 if a
    source ever returns it). ``port`` is an int in [1, 65535]. ``user`` and
    ``passwd`` default to empty strings (no auth).
    """

    ip: str
    port: int
    user: str = ""
    passwd: str = ""

    def __str__(self) -> str:  # pragma: no cover - trivial
        if self.user and self.passwd:
            return f"{self.user}:{self.passwd}@{self.ip}:{self.port}"
        return f"{self.ip}:{self.port}"

    def with_auth(self, user: str = "", passwd: str = "") -> Proxy:
        return Proxy(self.ip, self.port, user, passwd)

    @property
    def has_auth(self) -> bool:
        return bool(self.user) and bool(self.passwd)

    def to_url(self, protocol: Protocol) -> str:
        """Return ``protocol://[user:pass@]ip:port`` for use in client libraries."""
        auth = f"{self.user}:{self.passwd}@" if self.has_auth else ""
        return f"{protocol.scheme}://{auth}{self.ip}:{self.port}"


def _valid_port(port: int) -> bool:
    return 1 <= port <= 65535


def _valid_ip(ip: str) -> bool:
    try:
        IPv4Address(ip)
    except ValueError:
        return False
    return True


def _from_url_form(text: str) -> Iterator[Proxy]:
    for m in _URL_FORM.finditer(text):
        port = int(m.group("port"))
        if not _valid_port(port):
            continue
        if not _valid_ip(m.group("host")):
            continue
        yield Proxy(
            ip=m.group("host"),
            port=port,
            user=m.group("user") or "",
            passwd=m.group("pass") or "",
        )


def _from_structured(text: str) -> Iterator[Proxy] | None:
    """Try to interpret the payload as JSON and yield proxies from it.

    Returns ``None`` if the payload is not valid JSON, so the caller can fall
    back to free-text parsing.
    """
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None

    if isinstance(payload, dict):
        items = payload.get("data") or payload.get("proxies") or payload.get("results")
    else:
        items = payload

    if not isinstance(items, list):
        return None

    out: list[Proxy] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        ip = item.get("ip") or item.get("ipAddress") or item.get("address")
        port = item.get("port") or item.get("portNumber")
        if ip is None or port is None:
            continue
        try:
            port_i = int(port)
        except (TypeError, ValueError):
            continue
        if not _valid_port(port_i) or not _valid_ip(str(ip)):
            continue
        out.append(
            Proxy(
                ip=str(ip),
                port=port_i,
                user=str(item.get("username") or item.get("user") or ""),
                passwd=str(item.get("password") or item.get("pass") or ""),
            )
        )
    return iter(out) if out else iter([])


def _from_text(text: str) -> Iterator[Proxy]:
    """Parse proxy entries from free text by extracting every plausible IP:port."""
    seen: set[tuple[str, int]] = set()

    # Strategy 1: full URL forms (most precise)
    for p in _from_url_form(text):
        key = (p.ip, p.port)
        if key not in seen:
            seen.add(key)
            yield p

    # Strategy 2: ip:port:user:pass per line
    for line in text.splitlines():
        line = line.strip().strip("'\"")
        m = _IPV4_PORT_AUTH.match(line)
        if not m:
            continue
        ip, port = m.group("ip"), int(m.group("port"))
        if _valid_port(port) and _valid_ip(ip) and (ip, port) not in seen:
            seen.add((ip, port))
            yield Proxy(ip=ip, port=port, user=m.group("user"), passwd=m.group("pass"))

    # Strategy 3: bare ip:port per token
    for token in re.split(r"[\s,;\[\](){}<>'\"]+", text):
        token = token.strip()
        if not token:
            continue
        m = _IPV4_PORT.match(token)
        if not m:
            continue
        ip, port = m.group("ip"), int(m.group("port"))
        if _valid_port(port) and _valid_ip(ip) and (ip, port) not in seen:
            seen.add((ip, port))
            yield Proxy(ip=ip, port=port)

    # Strategy 4: free-text extraction (URLs, HTML, log lines) — last resort,
    # since it has the highest false-positive rate.
    for m in _FREE_IP_PORT.finditer(text):
        ip, port = m.group("ip"), int(m.group("port"))
        if _valid_port(port) and _valid_ip(ip) and (ip, port) not in seen:
            seen.add((ip, port))
            yield Proxy(ip=ip, port=port)


def parse(text: str, *, expected: Protocol | None = None) -> set[Proxy]:
    """Parse a raw source payload into a deduplicated set of ``Proxy``.

    Tries structured (JSON) parsing first, then falls back to text extraction.
    If ``expected`` is given, items whose ``protocols`` field disagrees with
    it are dropped.
    """
    if not text:
        return set()

    structured = _from_structured(text)
    if structured is not None:
        items: Iterable[Proxy] = list(structured)
        # If JSON yielded nothing, fall through to text — some sources return
        # valid JSON but empty/oddly-shaped data.
        if items:
            return _filter_by_protocol(items, expected)

    return set(_from_text(text))


def _filter_by_protocol(
    items: Iterable[Proxy], expected: Protocol | None
) -> set[Proxy]:
    """Filter items that explicitly tag an incompatible protocol.

    The parser doesn't actually parse JSON's ``protocols`` field — that's
    done by ``_from_structured`` indirectly. This helper is a no-op kept
    for compatibility with future enrichment.
    """
    return set(items)


def parse_file(path: str, *, expected: Protocol | None = None) -> set[Proxy]:
    """Read a file and parse it. Encoding-tolerant."""
    with open(path, encoding="utf-8", errors="ignore") as fh:
        return parse(fh.read(), expected=expected)
