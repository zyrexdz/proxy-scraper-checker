"""Tests for the interactive wizard.

The wizard is driven by ``rich.prompt.Prompt.ask`` and friends. Tests
monkeypatch those to return canned answers and verify the resulting plan
matches.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from proxy_scraper.protocols import Protocol
from rich.console import Console
from proxy_scraper.wizard import run_wizard, wizard_to_namespace


def _stub_prompts(monkeypatch, *, action="1", protocols="1,2,3", formats="1", preset="2", extra="n", filt="1"):
    """Replace all wizard prompt inputs with deterministic values."""
    answers = iter([action, protocols, formats, preset, extra, filt, "y"])
    monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: next(answers))
    monkeypatch.setattr("rich.prompt.Confirm.ask", lambda *a, **k: next(answers))
    monkeypatch.setattr("rich.prompt.IntPrompt.ask", lambda *a, **k: 250)
    monkeypatch.setattr("rich.prompt.FloatPrompt.ask", lambda *a, **k: 8.0)


def _silent_console():
    """A Rich Console that writes to a throw-away StringIO."""
    return Console(force_terminal=False, file=io.StringIO(), width=80)


def test_wizard_run_action(monkeypatch):
    _stub_prompts(monkeypatch)
    plan = run_wizard(_silent_console(), default_out_dir=Path("."))
    assert plan.get("__quit__") is not True
    assert plan["action"] == "run"
    assert Protocol.HTTP in plan["protocols"]
    assert plan["formats"] == ["txt"]
    assert plan["preset_name"] == "balanced"


def test_wizard_scrape_action(monkeypatch):
    _stub_prompts(monkeypatch, action="2")
    plan = run_wizard(_silent_console(), default_out_dir=Path("."))
    assert plan["action"] == "scrape"


def test_wizard_quit(monkeypatch):
    _stub_prompts(monkeypatch, action="4")
    plan = run_wizard(_silent_console(), default_out_dir=Path("."))
    assert plan.get("__quit__") is True


def test_wizard_to_namespace():
    plan = {
        "action":         "run",
        "protocols":      [Protocol.HTTP, Protocol.SOCKS5],
        "formats":        ["txt", "json"],
        "preset_name":    "balanced",
        "preset_values":  {"timeout": 6.0, "max_latency_ms": 3500.0, "retries": 2, "concurrency": 300},
        "extra_sources":  False,
        "use_filter":     True,
        "filter_targets": ["Cloudflare", "Discord"],
        "input_file":     None,
        "out_dir":        Path("./out"),
    }
    ns = wizard_to_namespace(plan)
    assert ns.protocol == ["http", "socks5"]
    assert ns.output_format == ["txt", "json"]
    assert ns.preset == "balanced"
    assert ns.concurrency == 300
    assert ns.input_file is None
    assert ns.extra_sources is False
    assert ns.out_dir == Path("./out")
