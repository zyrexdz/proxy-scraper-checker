"""Small helpers used across modules."""

from __future__ import annotations

import contextlib
import os
import sys

from .parser import Proxy
from .protocols import Protocol


def raise_fd_limit_windows() -> None:
    """Bump the WinSock file-descriptor limit on Windows.

    The default is 512, which is far too low for a 200-connection checker
    pool. The hard cap is per-process; on most desktop SKUs we can take it to
    8192. No-op on non-Windows.
    """
    if sys.platform != "win32":
        return
    with contextlib.suppress(OSError, ImportError):
        import ctypes

        windll = ctypes.WinDLL("ws2_32", use_last_error=True)
        # _setmaxstdio: bump CRT-level FILE* limit (0..2048 in modern CRT).
        with contextlib.suppress(AttributeError):
            windll._setmaxstdio(2048)


def cpu_count() -> int:
    """Return the number of usable CPUs, capped to keep responsiveness on shared hosts."""
    n = os.cpu_count() or 1
    return max(1, n)


def humanize_count(n: int) -> str:
    return f"{n:,}"


def proxy_url(proxy: Proxy, protocol: Protocol) -> str:
    """Build a ``protocol://[user:pass@]ip:port`` URL for client libraries."""
    return proxy.to_url(protocol)
