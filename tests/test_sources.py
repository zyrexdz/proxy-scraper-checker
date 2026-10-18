"""Tests for the source catalog and the persistent health ledger."""

from __future__ import annotations

from pathlib import Path

from proxy_scraper.protocols import Protocol
from proxy_scraper.sources import Source, SourceHealth, SourceHealthBook, sources_for


def test_sources_for_filters_by_protocol() -> None:
    http = sources_for([Protocol.HTTP])
    socks5 = sources_for([Protocol.SOCKS5])
    assert all(s.protocol == Protocol.HTTP for s in http)
    assert all(s.protocol == Protocol.SOCKS5 for s in socks5)


def test_source_key_stable() -> None:
    s1 = Source("https://example.com/list", Protocol.HTTP)
    s2 = Source("https://example.com/list", Protocol.HTTP)
    assert s1.key == s2.key


def test_source_health_success_increments() -> None:
    h = SourceHealth(key="test:url")
    h.record_success(count=10)
    h.record_success(count=5)
    assert h.successes == 2
    assert h.last_seen_count == 5


def test_source_health_failure_marks_stale_after_threshold() -> None:
    h = SourceHealth(key="test:url")
    for _ in range(4):
        h.record_failure()
    assert not h.is_stale
    h.record_failure()
    assert h.is_stale


def test_success_resets_consecutive_failures() -> None:
    h = SourceHealth(key="test:url")
    for _ in range(5):
        h.record_failure()
    assert h.is_stale
    h.record_success(count=1)
    assert not h.is_stale
    assert h.consecutive_failures == 0


def test_health_book_persists(tmp_path: Path) -> None:
    path = tmp_path / "health.json"
    book = SourceHealthBook(path=path, auto_load=False)
    src = Source("https://example.com", Protocol.HTTP)
    book.record_success(src, count=42)
    book.record_failure(src)
    book.save()

    # Reload
    reloaded = SourceHealthBook(path=path)
    h = reloaded.get(src)
    assert h.successes == 1
    assert h.failures == 1
    assert h.last_seen_count == 42


def test_health_book_handles_corrupt_file(tmp_path: Path) -> None:
    path = tmp_path / "health.json"
    path.write_text("not json at all", encoding="utf-8")
    book = SourceHealthBook(path=path)
    assert book.snapshot() == {}  # started fresh


def test_minimal_toml_parser_basic() -> None:
    from proxy_scraper.config import _parse_toml_minimal

    text = """
        [scraper]
        timeout = 30.0
        concurrency = 100

        [checker]
        retries = 5
    """
    data = _parse_toml_minimal(text)
    assert data["scraper"]["timeout"] == 30.0
    assert data["scraper"]["concurrency"] == 100
    assert data["checker"]["retries"] == 5


def test_minimal_toml_parser_list() -> None:
    from proxy_scraper.config import _parse_toml_minimal

    data = _parse_toml_minimal('output_formats = ["txt", "json"]')
    assert data["output_formats"] == ["txt", "json"]
