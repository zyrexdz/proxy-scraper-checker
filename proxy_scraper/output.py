"""Output writers.

Persists the validated proxy set in the user's chosen format(s). Each format
has trade-offs:

    - txt        compact, human-readable, what every existing tool consumes
    - txt-url    same line count, but `protocol://user:pass@ip:port` is what
                 modern HTTP clients expect (curl --proxy, requests, mitmproxy)
    - json       metadata per proxy — best for piping into other tools and
                 for post-run analysis
    - csv        spreadsheet-friendly, easy to filter by country/anonymity
"""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable
from datetime import date
from pathlib import Path

from .checker import CheckResult
from .parser import Proxy
from .protocols import Protocol


def _default_dir(out_dir: Path | None) -> Path:
    return Path(out_dir) if out_dir is not None else Path(".")


def _today_name(stem: str, ext: str, out_dir: Path | None) -> Path:
    return _default_dir(out_dir) / f"{stem}_{date.today().isoformat()}.{ext}"


def write_txt(
    results: Iterable[CheckResult], out_dir: Path | None = None
) -> list[Path]:
    """Write one file per protocol: ``working_<proto>_<date>.txt``."""
    bucket: dict[Protocol, list[str]] = {}
    for r in results:
        if not r.ok:
            continue
        bucket.setdefault(r.protocol, []).append(_addr_line(r.proxy))

    out: list[Path] = []
    for proto, addrs in bucket.items():
        if not addrs:
            continue
        path = _today_name(f"working_{proto.label.lower()}", "txt", out_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(sorted(set(addrs))) + "\n", encoding="utf-8")
        out.append(path)
    return out


def write_txt_url(
    results: Iterable[CheckResult], out_dir: Path | None = None
) -> list[Path]:
    """Write one file per protocol: ``working_<proto>_url_<date>.txt``.

    Format: ``socks5://user:pass@1.2.3.4:1080`` per line.
    """
    bucket: dict[Protocol, list[str]] = {}
    for r in results:
        if not r.ok:
            continue
        bucket.setdefault(r.protocol, []).append(r.proxy.to_url(r.protocol))

    out: list[Path] = []
    for proto, urls in bucket.items():
        if not urls:
            continue
        path = _today_name(f"working_{proto.label.lower()}_url", "txt", out_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(sorted(set(urls))) + "\n", encoding="utf-8")
        out.append(path)
    return out


def write_json(
    results: Iterable[CheckResult], out_dir: Path | None = None
) -> list[Path]:
    """Write a single JSON file with full metadata per proxy."""
    data = [r.to_dict() for r in results if r.ok]
    if not data:
        return []
    path = _today_name("working_all", "json", out_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return [path]


def write_csv(
    results: Iterable[CheckResult], out_dir: Path | None = None
) -> list[Path]:
    """Write a single CSV file with header row."""
    rows = [r.to_dict() for r in results if r.ok]
    if not rows:
        return []
    path = _today_name("working_all", "csv", out_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["ip", "port", "protocol", "user", "passwd", "latency_ms", "country", "anonymity"]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            row["protocol"] = row["protocol"]  # keep as string
            writer.writerow(row)
    return [path]


def write_combined(
    results: Iterable[CheckResult], out_dir: Path | None = None
) -> list[Path]:
    """Write a single TXT file with every working proxy, all protocols mixed."""
    lines = sorted({_addr_line(r.proxy) for r in results if r.ok})
    if not lines:
        return []
    path = _today_name("working_all", "txt", out_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return [path]


def _addr_line(p: Proxy) -> str:
    if p.has_auth:
        return f"{p.user}:{p.passwd}@{p.ip}:{p.port}"
    return f"{p.ip}:{p.port}"


# Format registry — used by the CLI to map user-friendly names to writers.
WRITERS = {
    "txt": write_txt,
    "txt-url": write_txt_url,
    "json": write_json,
    "csv": write_csv,
    "combined": write_combined,
}


def write_all(
    results: Iterable[CheckResult], *, formats: list[str], out_dir: Path | None = None
) -> list[Path]:
    """Invoke each requested writer and return the combined list of files written."""
    written: list[Path] = []
    results = list(results)
    for fmt in formats:
        writer = WRITERS.get(fmt)
        if writer is None:
            continue
        written.extend(writer(results, out_dir))
    return written
