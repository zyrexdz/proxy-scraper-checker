"""Smoke tests for the CLI.

These run the argparse layer end-to-end and verify the dispatch path
doesn't crash. They do NOT trigger a real scrape or check (no network).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from proxy_scraper.cli import build_parser, main
from proxy_scraper.protocols import ALL_PROTOCOLS


def test_help_runs(capsys: pytest.CaptureFixture) -> None:
    """``--help`` should print help and exit 0."""
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "usage:" in out.lower()
    assert "--protocol" in out
    assert "--preset" in out
    assert "--no-color" in out


def test_version_runs(capsys: pytest.CaptureFixture) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "3." in out  # 3.0.0


def test_parser_no_args_defaults_to_run() -> None:
    """``main.py`` with no args should parse as a 'run' command (not crash)."""
    from proxy_scraper.cli import _resolve_command

    parser = build_parser()
    args = parser.parse_args([])
    assert _resolve_command(args) == "run"
    assert args.input_file is None
    assert args.protocol is None
    assert args.preset == "recommended"
    assert args.no_color is False
    assert args.non_interactive is False
    assert args.out_dir == Path(".")
    assert args.config.name == "config.toml"


def test_parser_scrape_flag_sets_mode() -> None:
    from proxy_scraper.cli import _resolve_command

    parser = build_parser()
    args = parser.parse_args(["--scrape"])
    assert _resolve_command(args) == "scrape"


def test_parser_input_file_sets_check_mode(tmp_path) -> None:
    from proxy_scraper.cli import _resolve_command

    proxy_file = tmp_path / "proxies.txt"
    proxy_file.write_text("1.2.3.4:8080\n", encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args([str(proxy_file), "--non-interactive"])
    assert _resolve_command(args) == "check"
    assert args.input_file == proxy_file
    assert args.non_interactive is True


def test_parser_scrape_with_input_file_errors() -> None:
    from proxy_scraper.cli import _resolve_command

    parser = build_parser()
    args = parser.parse_args(["--scrape", "proxies.txt"])
    with pytest.raises(SystemExit) as exc:
        _resolve_command(args)
    assert exc.value.code != 0


def test_parser_protocol_can_repeat() -> None:
    parser = build_parser()
    args = parser.parse_args(["-p", "http", "-p", "socks5"])
    assert args.protocol == ["http", "socks5"]


def test_parser_protocol_invalid_rejected() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["-p", "telnet"])
    assert exc.value.code == 2


def test_parser_preset_valid() -> None:
    parser = build_parser()
    for preset in ("ultimate", "balanced", "recommended", "catch-all"):
        args = parser.parse_args(["--preset", preset])
        assert args.preset == preset


def test_parser_output_format_repeatable() -> None:
    parser = build_parser()
    args = parser.parse_args(["-f", "json", "-f", "csv"])
    assert args.output_format == ["json", "csv"]


def test_all_protocols_have_strings() -> None:
    """Protocol enum members must have lowercase string values usable as choices."""
    for p in ALL_PROTOCOLS:
        assert isinstance(p.value, str)
        assert p.value == p.value.lower()


def test_main_no_args_does_not_crash_attrerror(capsys: pytest.CaptureFixture) -> None:
    """Regression: argparse subparser struct meant args.no_color didn't exist
    when no subcommand was given. Make sure that's gone."""
    # We can't run a real main() because that triggers the actual scrape.
    # Instead, just confirm parsing succeeds and all expected attrs are present.
    parser = build_parser()
    args = parser.parse_args([])
    for required in (
        "no_color", "non_interactive", "extra_sources", "enrich",
        "protocol", "preset", "timeout", "max_latency", "retries",
        "concurrency", "output_format", "out_dir", "config",
    ):
        assert hasattr(args, required), f"args.{required} missing"


def test_scrape_message_singular_plural() -> None:
    """The status line pluralizes 'source' and 'protocol' correctly."""
    from proxy_scraper.cli import _scrape_status_line

    assert _scrape_status_line(1, ["http"]) == "Scraping 1 source across 1 protocol."
    assert _scrape_status_line(150, ["http", "socks4", "socks5"]) == "Scraping 150 sources across 3 protocols."
    assert _scrape_status_line(2, ["http"]) == "Scraping 2 sources across 1 protocol."
