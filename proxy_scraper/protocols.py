"""Protocol constants and parsing.

A "protocol" identifies the wire-level scheme a proxy speaks: http(s), socks4,
or socks5. The scraper is protocol-agnostic at the URL level — sources are
tagged with a protocol bucket so the checker can route the right scheme — but
in practice most public lists mix HTTP and HTTPS together under the http bucket.
"""

from __future__ import annotations

from enum import Enum
from typing import Final


class Protocol(str, Enum):
    """Supported proxy protocols.

    Inheriting from ``str`` lets these values be used directly in URL builders
    (``f"{proto}://{addr}"``) and in equality checks against raw strings.
    """

    HTTP = "http"
    SOCKS4 = "socks4"
    SOCKS5 = "socks5"

    @property
    def scheme(self) -> str:
        """Return the URL scheme used by ``requests``/``aiohttp`` for this protocol."""
        return {
            Protocol.HTTP: "http",  # covers both http:// and https://
            Protocol.SOCKS4: "socks4",
            Protocol.SOCKS5: "socks5h",  # 'h' = resolve hostnames remotely
        }[self]

    @property
    def label(self) -> str:
        """Human-facing display name."""
        return {
            Protocol.HTTP: "HTTP",
            Protocol.SOCKS4: "SOCKS4",
            Protocol.SOCKS5: "SOCKS5",
        }[self]

    @classmethod
    def parse(cls, raw: str) -> "Protocol":
        """Parse a user-provided string (``"http"``, ``"socks5"``, ``"HTTPS"``).

        Whitespace and case are ignored. Raises ``ValueError`` for unknown input.
        """
        norm = raw.strip().lower().replace(" ", "")
        if norm in ("http", "https"):
            return cls.HTTP
        if norm in ("socks4", "socks4a"):
            return cls.SOCKS4
        if norm in ("socks5", "socks5h"):
            return cls.SOCKS5
        raise ValueError(f"unknown proxy protocol: {raw!r}")


ALL_PROTOCOLS: Final[tuple[Protocol, ...]] = (
    Protocol.HTTP,
    Protocol.SOCKS4,
    Protocol.SOCKS5,
)
