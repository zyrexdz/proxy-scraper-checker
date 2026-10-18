"""Tests for the plain-text progress reporter and dashboard."""

from __future__ import annotations

import io
import sys

import pytest

from proxy_scraper.ui import SimpleDashboard, SimpleProgress


class _FakeStderr:
    """Minimal stderr stand-in that captures writes and reports a TTY state."""

    def __init__(self, *, is_tty: bool) -> None:
        self._buf = io.StringIO()
        self._is_tty = is_tty

    def write(self, s: str) -> int:
        return self._buf.write(s)

    def flush(self) -> None:
        self._buf.flush()

    def isatty(self) -> bool:
        return self._is_tty

    def getvalue(self) -> str:
        return self._buf.getvalue()


@pytest.fixture
def captured_stderr(monkeypatch: pytest.MonkeyPatch):
    """Replace sys.stderr with a buffer and yield the buffer."""
    fake = _FakeStderr(is_tty=False)
    monkeypatch.setattr(sys, "stderr", fake)
    return fake


def test_simple_progress_line_per_update_when_not_tty(capsys: pytest.CaptureFixture) -> None:
    """When stderr isn't a TTY, each update is its own line (no \r)."""
    import time as _t
    p = SimpleProgress("Scraping", total=5)
    p.start()
    for i in range(1, 6):
        p.update(i, extra="X proxies")
        _t.sleep(0.25)  # exceed the 0.2s throttle
    p.finish("done")
    out = capsys.readouterr().err
    # Each update is on its own line — no \r overwriting.
    assert out.count("\n") >= 5
    assert "  0.0%  0/5" in out
    assert "100.0%  5/5" in out
    assert "[done] Scraping complete" in out


def test_simple_progress_tty_mode_uses_cr(capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    """When stderr IS a TTY, updates overwrite in place using \r."""
    fake = _FakeStderr(is_tty=True)
    # Capsys already captured stderr; monkeypatching after is fine because
    # SimpleProgress reads sys.stderr.isatty() at __init__ time.
    monkeypatch.setattr(sys, "stderr", fake)
    p = SimpleProgress("Scraping", total=5)
    p.start()
    p.update(5)
    p.finish("done")
    out = fake.getvalue()
    assert "\r" in out


def test_simple_dashboard_basic(capsys: pytest.CaptureFixture) -> None:
    import time as _t
    d = SimpleDashboard(total=10, label="http", threads=200)
    d.start()
    for i in range(1, 11):
        d.update(checked=i, working=i // 2)
        _t.sleep(0.25)
    d.finish(total_working=5)
    out = capsys.readouterr().err
    assert "working=0" in out
    assert "working=5" in out
    assert "[done] Validation complete" in out
    assert "5 working" in out


def test_simple_progress_final_summary_on_stdout(capsys: pytest.CaptureFixture) -> None:
    """The user-facing summary goes to stdout (not stderr) so it survives 2>&1 redirect."""
    p = SimpleProgress("Scraping", total=3)
    p.start()
    p.update(3)
    p.finish("Scraped 1000 proxies from 3 sources")
    captured = capsys.readouterr()
    # Final summary on stdout.
    assert "Scraped 1000 proxies from 3 sources" in captured.out
    # Progress / [done] line on stderr.
    assert "[done] Scraping complete" in captured.err


def test_summary_table_markup_balanced() -> None:
    """Regression: rows in summary_table must keep Rich markup balanced.

    Tags that include style arguments (``[bold #00e5a8]``) must be closed
    with ``[/]``, NOT with ``[/bold]`` — those are mismatched and Rich
    raises ``MarkupError`` while measuring column widths.
    """
    from proxy_scraper.anonymity import Anonymity

    # Build a fake CheckResult just to exercise the markup path.
    from proxy_scraper.checker import CheckResult
    from proxy_scraper.cli import _print_summary
    from proxy_scraper.parser import Proxy
    from proxy_scraper.protocols import Protocol

    results = [
        CheckResult(
            proxy=Proxy("1.2.3.4", 80),
            protocol=Protocol.HTTP,
            latency_ms=120.0,
            anonymity=Anonymity.ELITE,
            ok=True,
        )
    ]
    # If the markup is unbalanced, console.print in _print_summary raises.
    try:
        _print_summary(results, [])
    except Exception as e:
        pytest.fail(f"_print_summary raised: {type(e).__name__}: {e}")


def test_console_initialization() -> None:
    """The module-level Console must initialize without crashing."""
    from proxy_scraper import ui
    assert ui.console is not None
    # On non-Windows it defaults; on Windows we always set legacy_windows
    # explicitly (True if VT enable failed, False if it succeeded).
    if sys.platform == "win32":
        assert ui.console.legacy_windows in (True, False)
