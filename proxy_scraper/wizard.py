"""Interactive configuration wizard.

Walks the user through every runtime option with numbered prompts, shows a
summary, and returns a populated plan ready to run.

Invoked by default when ``main.py`` runs with no flags. Bypass with
``--non-interactive`` (uses config.toml + flags).
"""

from __future__ import annotations

from pathlib import Path

from rich.box import HEAVY, ROUNDED
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, FloatPrompt, IntPrompt, Prompt
from rich.table import Table
from rich.text import Text

from .cli import PRESETS
from . import __version__
from .protocols import ALL_PROTOCOLS, Protocol
from .ui import CYAN, GREEN, MUTED, RED, YELLOW

_VALID_FORMATS = ["txt", "txt-url", "json", "csv", "combined"]


def _header(console: Console) -> None:
    head = Text()
    head.append("ZYRE ", style=f"bold {GREEN}")
    head.append("PROXY SCRAPER", style=f"bold {CYAN}")
    head.append("  ")
    head.append(f"v{__version__}", style=MUTED)
    console.print()
    console.print(Panel(head, box=HEAVY, border_style=GREEN, padding=(0, 2)))


def _prompt_action(console: Console) -> str:
    table = Table(
        box=ROUNDED,
        border_style=MUTED,
        header_style=f"bold {GREEN}",
        title="What next?",
        title_justify="left",
        padding=(0, 2),
    )
    table.add_column("#", justify="right", style=f"bold {CYAN}", width=3)
    table.add_column("Action")
    table.add_row("1", "Scrape + validate")
    table.add_row("2", "Scrape only (raw, no check)")
    table.add_row("3", "Validate a file")
    table.add_row("4", "Quit")
    console.print(table)
    choice = Prompt.ask("[bold]>[/] choice", choices=["1", "2", "3", "4"], default="1")
    return {"1": "run", "2": "scrape", "3": "check", "4": "quit"}[choice]


def _prompt_protocols(console: Console) -> list[Protocol]:
    table = Table(
        box=ROUNDED,
        border_style=MUTED,
        header_style=f"bold {GREEN}",
        title="Protocols",
        title_justify="left",
        padding=(0, 2),
    )
    table.add_column("#", justify="right", style=f"bold {CYAN}", width=3)
    table.add_column("Protocol")
    for i, p in enumerate(ALL_PROTOCOLS, 1):
        table.add_row(str(i), p.label)
    console.print(table)
    raw = Prompt.ask(
        "[bold]>[/] toggle (e.g. 1,3) — enter for all",
        default="1,2,3",
    )
    selected: list[Protocol] = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < len(ALL_PROTOCOLS):
                p = ALL_PROTOCOLS[idx]
                if p not in selected:
                    selected.append(p)
    return selected or list(ALL_PROTOCOLS)


def _prompt_formats(console: Console) -> list[str]:
    table = Table(
        box=ROUNDED,
        border_style=MUTED,
        header_style=f"bold {GREEN}",
        title="Output formats",
        title_justify="left",
        padding=(0, 2),
    )
    table.add_column("#", justify="right", style=f"bold {CYAN}", width=3)
    table.add_column("Format", style="bold")
    table.add_column("What you get")
    table.add_row("1", "txt",       "ip:port per line, one file per protocol")
    table.add_row("2", "txt-url",   "protocol://user:pass@ip:port per line")
    table.add_row("3", "json",      "one JSON file with ip/port/latency/country/anonymity")
    table.add_row("4", "csv",       "single CSV, spreadsheet-friendly")
    table.add_row("5", "combined",  "one TXT with every working proxy across all protocols")
    console.print(table)
    raw = Prompt.ask(
        "[bold]>[/] pick (e.g. 1,3) — enter for default (txt)",
        default="1",
    )
    selected: list[str] = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < len(_VALID_FORMATS):
                fmt = _VALID_FORMATS[idx]
                if fmt not in selected:
                    selected.append(fmt)
    return selected or ["txt"]


def _prompt_preset(console: Console) -> tuple[str, dict]:
    table = Table(
        box=ROUNDED,
        border_style=MUTED,
        header_style=f"bold {GREEN}",
        title="Quality preset",
        title_justify="left",
        padding=(0, 2),
    )
    table.add_column("#", justify="right", style=f"bold {CYAN}", width=3)
    table.add_column("Preset", style="bold")
    table.add_column("Timeout", justify="right")
    table.add_column("Max ping", justify="right")
    table.add_column("Tries")
    table.add_row("1", "ULTIMATE",    "3.0s",  "1500ms",  "1")
    table.add_row("2", "BALANCED",    "6.0s",  "3500ms",  "2")
    table.add_row("3", "RECOMMENDED", "8.0s",  "6000ms",  "3")
    table.add_row("4", "CATCH-ALL",   "15.0s", "12000ms", "3")
    table.add_row("5", "CUSTOM",      "-",     "-",       "-")
    console.print(table)
    choice = Prompt.ask("[bold]>[/] preset", choices=["1", "2", "3", "4", "5"], default="2")
    name = {"1": "ultimate", "2": "balanced", "3": "recommended", "4": "catch-all", "5": "custom"}[choice]
    if name != "custom":
        return name, PRESETS[name]
    console.print("[bold]Custom values[/]")
    threads = IntPrompt.ask("[bold]>[/] threads", default=250)
    timeout = FloatPrompt.ask("[bold]>[/] timeout per check (s)", default=8.0)
    max_ping = FloatPrompt.ask("[bold]>[/] max ping (ms)", default=5000.0)
    retries = IntPrompt.ask("[bold]>[/] retries", default=3)
    return name, dict(
        timeout=timeout,
        max_latency_ms=max_ping,
        retries=retries,
        concurrency=threads,
    )


def _prompt_filter(console: Console) -> tuple[bool, list[str]]:
    from .filter import DEFAULT_TARGETS

    keys = [s.name for s in DEFAULT_TARGETS]
    table = Table(
        box=ROUNDED,
        border_style=MUTED,
        header_style=f"bold {GREEN}",
        title="Target filter (drop proxies banned on these sites)",
        title_justify="left",
        padding=(0, 2),
    )
    table.add_column("#", justify="right", style=f"bold {CYAN}", width=3)
    table.add_column("Option")
    table.add_row("1", "skip filter")
    table.add_row("2", f"quick — Cloudflare, Discord, Google")
    table.add_row("3", f"full — all {len(keys)} targets (slower)")
    table.add_row("4", "custom — pick targets")
    console.print(table)
    choice = Prompt.ask("[bold]>[/] choice", choices=["1", "2", "3", "4"], default="1")
    if choice == "1":
        return False, []
    if choice == "2":
        return True, ["Cloudflare", "Discord", "Google"]
    if choice == "3":
        return True, keys
    target_table = Table(
        box=ROUNDED,
        border_style=MUTED,
        header_style=f"bold {GREEN}",
        title="Targets",
        title_justify="left",
        padding=(0, 2),
    )
    target_table.add_column("#", justify="right", style=f"bold {CYAN}", width=3)
    target_table.add_column("Service")
    for i, name in enumerate(keys, 1):
        target_table.add_row(str(i), name)
    console.print(target_table)
    raw = Prompt.ask("[bold]>[/] target numbers", default="1,2,5")
    selected: list[str] = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < len(keys):
                if keys[idx] not in selected:
                    selected.append(keys[idx])
    return True, (selected or ["Cloudflare", "Discord", "Google"])


def _summary_table(console: Console, plan: dict) -> None:
    console.print()
    table = Table(
        box=ROUNDED,
        border_style=GREEN,
        title="Plan",
        title_justify="left",
        padding=(0, 2),
    )
    table.add_column("Setting", style=f"bold {CYAN}")
    table.add_column("Value", style="bold white")
    for label, value in plan.items():
        table.add_row(label, value)
    console.print(table)


def _prompt_input_file(console: Console) -> Path | None:
    while True:
        raw = Prompt.ask("[bold]>[/] path to proxy file")
        p = Path(raw.strip())
        if p.is_file():
            return p
        console.print(f"  [{RED}]{p}[/{RED}] not found")
        if not Confirm.ask("[bold]>[/] try again?", default=True):
            return None


def run_wizard(console: Console, *, default_out_dir: Path | None = None) -> dict:
    """Walk the user through every option. Returns a dict of run kwargs.

    Returns ``{"__quit__": True}`` if the user picked Quit.
    """
    _header(console)

    action = _prompt_action(console)
    if action == "quit":
        return {"__quit__": True}

    protocols = _prompt_protocols(console)
    formats = _prompt_formats(console)
    preset_name, preset_vals = _prompt_preset(console)
    use_filter = False
    filter_targets: list[str] = []
    input_file: Path | None = None
    if action in ("run", "scrape"):
        use_filter, filter_targets = _prompt_filter(console)
    if action == "check":
        input_file = _prompt_input_file(console)
        if input_file is None:
            return {"__quit__": True}

    out_dir_default = default_out_dir or Path(".")
    plan = {
        "Action":       {"run": "scrape + validate", "scrape": "scrape only", "check": "validate file"}[action],
        "Protocols":    ", ".join(p.value for p in protocols),
        "Output":       ", ".join(formats) or "txt",
        "Preset":       f"{preset_name} (timeout {preset_vals['timeout']}s, max ping {preset_vals['max_latency_ms']:.0f}ms)",
        "Concurrency":  f"{preset_vals['concurrency']} threads",
        "Filter":       ", ".join(filter_targets) if use_filter else "off",
        "Output dir":   str(out_dir_default),
    }
    if action == "check":
        plan["Input file"] = str(input_file)
    _summary_table(console, plan)

    # MARKUP FIX: no argument on either opening or closing tag.
    if not Confirm.ask("[bold]>[/] run with this plan?", default=True):
        console.print(f"  [{YELLOW}]cancelled[/{YELLOW}]")
        return {"__quit__": True}

    return {
        "action":         action,
        "protocols":      protocols,
        "formats":        formats,
        "preset_name":    preset_name,
        "preset_values":  preset_vals,
        "extra_sources":  True,  # always include HTML scrapers now
        "use_filter":     use_filter,
        "filter_targets": filter_targets,
        "input_file":     input_file,
        "out_dir":        out_dir_default,
    }


def wizard_to_namespace(plan: dict) -> object:
    """Convert a wizard plan dict into an argparse.Namespace compatible with cmd_*."""
    import argparse

    ns = argparse.Namespace()
    ns.no_color = False
    ns.non_interactive = True
    ns.extra_sources = plan["extra_sources"]
    ns.config = Path("config.toml")
    ns.out_dir = plan["out_dir"]
    ns.output_format = plan["formats"]
    ns.protocol = [p.value for p in plan["protocols"]]
    ns.preset = plan["preset_name"]
    ns.timeout = None
    ns.max_latency = None
    ns.retries = None
    ns.concurrency = plan["preset_values"]["concurrency"]
    ns.input_file = plan["input_file"]
    ns.enrich = False
    return ns
