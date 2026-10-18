"""Tests for output writers."""

from __future__ import annotations

from pathlib import Path

from proxy_scraper.anonymity import Anonymity
from proxy_scraper.checker import CheckResult
from proxy_scraper.output import write_csv, write_json, write_txt, write_txt_url
from proxy_scraper.parser import Proxy
from proxy_scraper.protocols import Protocol


def _results() -> list[CheckResult]:
    return [
        CheckResult(
            proxy=Proxy("1.2.3.4", 80),
            protocol=Protocol.HTTP,
            latency_ms=120.5,
            samples_ms=(110.0, 131.0),
            anonymity=Anonymity.ELITE,
            country="US",
            ok=True,
        ),
        CheckResult(
            proxy=Proxy("5.6.7.8", 1080, "user", "pass"),
            protocol=Protocol.SOCKS5,
            latency_ms=84.0,
            ok=True,
        ),
        CheckResult(
            proxy=Proxy("9.9.9.9", 3128),
            protocol=Protocol.HTTP,
            ok=False,  # should be excluded from outputs
        ),
    ]


def test_write_txt_per_protocol(tmp_path: Path) -> None:
    paths = write_txt(_results(), out_dir=tmp_path)
    names = {p.name for p in paths}
    assert any(name.startswith("working_http_") for name in names)
    assert any(name.startswith("working_socks5_") for name in names)

    # Each file has exactly the working proxies, one per line.
    for p in paths:
        content = p.read_text(encoding="utf-8").strip().splitlines()
        if p.name.startswith("working_http_"):
            assert "1.2.3.4:80" in content
        else:
            assert "user:pass@5.6.7.8:1080" in content


def test_write_txt_url_uses_scheme(tmp_path: Path) -> None:
    paths = write_txt_url(_results(), out_dir=tmp_path)
    for p in paths:
        content = p.read_text(encoding="utf-8").strip().splitlines()
        if p.name.startswith("working_socks5_"):
            assert "socks5h://user:pass@5.6.7.8:1080" in content


def test_write_json_includes_metadata(tmp_path: Path) -> None:
    paths = write_json(_results(), out_dir=tmp_path)
    assert len(paths) == 1
    import json as _json

    data = _json.loads(paths[0].read_text(encoding="utf-8"))
    assert len(data) == 2  # only working
    by_ip = {d["ip"]: d for d in data}
    assert by_ip["1.2.3.4"]["latency_ms"] == 120.5
    assert by_ip["1.2.3.4"]["country"] == "US"
    assert by_ip["1.2.3.4"]["anonymity"] == "elite"


def test_write_csv(tmp_path: Path) -> None:
    paths = write_csv(_results(), out_dir=tmp_path)
    assert len(paths) == 1
    text = paths[0].read_text(encoding="utf-8")
    assert "ip,port,protocol" in text.splitlines()[0]
    assert "1.2.3.4,80,http,US,elite" in text.replace(" ", "") or "1.2.3.4,80,http" in text


def test_write_txt_skips_empty_protocols(tmp_path: Path) -> None:
    only_socks4 = [
        CheckResult(proxy=Proxy("1.2.3.4", 1080), protocol=Protocol.SOCKS4, ok=False),
    ]
    paths = write_txt(only_socks4, out_dir=tmp_path)
    assert paths == []
