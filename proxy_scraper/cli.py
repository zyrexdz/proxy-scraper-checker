"""Command-line interface and pipeline orchestrator.

Two workflows are supported:

    - ``scrape``: pull proxies from configured sources and write them raw to
      disk (no validation). Useful as a fast first pass.
    - ``check``: validate a previously scraped file (or any file of proxy
      addresses in ``ip:port`` format) and write the working subset.
    - ``run``:   full pipeline — scrape + validate (default).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path
from typing import Sequence

import aiohttp

from . import __version__
from .checker import CheckResult, check_all, enrich_results
from .config import Config
from .filter import DEFAULT_TARGETS, filter_targets, targets_by_names
from .output import write_all
from .parser import Proxy, parse_file
from .protocols import ALL_PROTOCOLS, Protocol
from .scraper import scrape as scrape_sources
from .sources import SourceHealthBook, sources_by_protocol
from .ui import (
    GREEN,
    MUTED,
    RED,
    YELLOW,
    SimpleDashboard,
    SimpleProgress,
    banner,
    console,
    summary_table,
)
from .utils import cpu_count, raise_fd_limit_windows


# ---------------------------------------------------------------------------
# Quality presets — exposed as CLI choices for ``--preset``.
# ---------------------------------------------------------------------------

PRESETS = {
    "ultimate":  dict(timeout=3.0, max_latency_ms=1500.0, retries=1, concurrency=400),
    "balanced":  dict(timeout=6.0, max_latency_ms=3500.0, retries=2, concurrency=300),
    "recommended": dict(timeout=8.0, max_latency_ms=6000.0, retries=3, concurrency=250),
    "catch-all": dict(timeout=15.0, max_latency_ms=12000.0, retries=3, concurrency=150),
}


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser.

    Single parser, no subcommands. The pipeline mode is inferred:

        * ``python main.py``                       -> run   (scrape + validate)
        * ``python main.py --scrape``              -> scrape (raw, no validation)
        * ``python main.py proxies.txt``           -> check (validate the file)
        * ``python main.py --scrape proxies.txt``  -> error (modes are exclusive)
    """
    parser = argparse.ArgumentParser(
        prog="zyre-proxy-scraper",
        description="Scrape and validate free public proxies across HTTP, SOCKS4, SOCKS5.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--scrape",
        action="store_true",
        help="Scrape only (no validation). Without this flag, the default is 'run' (scrape+validate).",
    )
    parser.add_argument(
        "input_file",
        nargs="?",
        default=None,
        type=Path,
        help="(check mode) Path to a file containing proxies (one per line, ip:port format).",
    )
    parser.add_argument(
        "--protocol", "-p",
        action="append",
        choices=[p.value for p in ALL_PROTOCOLS],
        help="Protocol to scrape. Repeatable. Default: all.",
    )
    parser.add_argument("--preset", choices=list(PRESETS), default="recommended")
    parser.add_argument("--timeout", type=float, help="Override preset timeout (seconds).")
    parser.add_argument("--max-latency", type=float, help="Override preset max latency (ms).")
    parser.add_argument("--retries", type=int, help="Override preset retries.")
    parser.add_argument("--concurrency", type=int, help="Override concurrency.")
    parser.add_argument(
        "--output-format", "-f",
        action="append",
        choices=["txt", "txt-url", "json", "csv", "combined"],
        help="Output format(s). Repeatable. Default: txt.",
    )
    parser.add_argument("--out-dir", type=Path, default=Path("."), help="Directory to write outputs to.")
    parser.add_argument("--config", type=Path, default=Path("config.toml"), help="Config file path.")
    parser.add_argument("--non-interactive", action="store_true", help="Disable all prompts; use defaults / config.")
    parser.add_argument("--no-color", action="store_true", help="Disable Rich colors.")
    parser.add_argument("--extra-sources", action="store_true", help="Include HTML scraper sources (experimental).")
    parser.add_argument("--enrich", action="store_true", help="Force-enable anonymity + geo enrichment (overrides config).")
    return parser


def _resolve_command(args: argparse.Namespace) -> str:
    """Pick the pipeline mode from the parsed args."""
    if args.scrape and args.input_file is not None:
        raise SystemExit("error: --scrape and an input file are mutually exclusive")
    if args.scrape:
        return "scrape"
    if args.input_file is not None:
        return "check"
    return "run"


def _apply_preset(args: argparse.Namespace) -> dict:
    preset = PRESETS[args.preset]
    return {
        "timeout": args.timeout if args.timeout is not None else preset["timeout"],
        "max_latency_ms": args.max_latency if args.max_latency is not None else preset["max_latency_ms"],
        "retries": args.retries if args.retries is not None else preset["retries"],
        "concurrency": args.concurrency if args.concurrency is not None else preset["concurrency"],
    }


def _select_protocols(args: argparse.Namespace) -> list[Protocol]:
    raw = args.protocol or [p.value for p in ALL_PROTOCOLS]
    return [Protocol.parse(p) for p in raw]


# ---------------------------------------------------------------------------
# Pipeline phases.
# ---------------------------------------------------------------------------

def _scrape_status_line(total_sources: int, protocols) -> str:
    """Build the scrape-start status line with correct singular/plural."""
    proto_word = "protocol" if len(protocols) == 1 else "protocols"
    src_word = "source" if total_sources == 1 else "sources"
    return f"Scraping {total_sources} {src_word} across {len(protocols)} {proto_word}."


async def _do_scrape(
    protocols: list[Protocol],
    config: Config,
    *,
    include_extra: bool,
) -> dict[Protocol, set[Proxy]]:
    by_proto = sources_by_protocol(protocols, include_extra=include_extra)
    total_sources = sum(len(v) for v in by_proto.values())
    console.print(f"  [bold]{_scrape_status_line(total_sources, protocols)}[/bold]")

    progress = SimpleProgress("Scraping", total_sources)
    progress.start()

    sources = tuple(src for srcs in by_proto.values() for src in srcs)

    from .sources import Source
    from .parser import parse as parse_payload
    from .scraper import _pick_headers

    sem = asyncio.Semaphore(config.scraper.concurrency)
    out: dict[Protocol, set[Proxy]] = {p: set() for p in protocols}
    health = SourceHealthBook(auto_load=True)
    found = 0

    connector = aiohttp.TCPConnector(limit=config.scraper.concurrency * 2, ttl_dns_cache=300, ssl=False)

    async with aiohttp.ClientSession(connector=connector) as session:
        async def run(source: Source) -> None:
            nonlocal found
            async with sem:
                if health.is_stale(source):
                    progress.update(progress._done + 1, extra=f"{found:,} proxies")
                    return
                try:
                    async with session.get(
                        source.url,
                        headers=_pick_headers(source),
                        timeout=aiohttp.ClientTimeout(total=config.scraper.timeout),
                    ) as resp:
                        if resp.status == 200:
                            text = await resp.text(errors="ignore")
                            parsed = parse_payload(text, expected=source.protocol)
                            if parsed:
                                out[source.protocol].update(parsed)
                                health.record_success(source, count=len(parsed))
                                found += len(parsed)
                            else:
                                health.record_failure(source)
                        else:
                            health.record_failure(source)
                except (asyncio.TimeoutError, aiohttp.ClientError, Exception):
                    health.record_failure(source)
                finally:
                    progress.update(progress._done + 1, extra=f"{found:,} proxies")

        await asyncio.gather(*(run(s) for s in sources))

    # Compute the deduped count once the work is done so the summary line
    # matches the table that ``cmd_run`` / ``cmd_scrape`` will print next.
    unique_total = sum(len(v) for v in out.values())
    progress.finish(
        f"Scraped {unique_total:,} unique proxies from {total_sources} "
        f"{'source' if total_sources == 1 else 'sources'}"
    )
    health.save()
    return out


async def _do_check(
    scraped: dict[Protocol, set[Proxy]],
    preset_args: dict,
    *,
    show_dashboard: bool = True,
) -> list[CheckResult]:
    timeout = preset_args["timeout"]
    max_latency_ms = preset_args["max_latency_ms"]
    retries = preset_args["retries"]
    concurrency = preset_args["concurrency"]

    flat: list[tuple[Proxy, Protocol]] = [
        (p, proto) for proto in sorted(scraped) for p in scraped[proto]
    ]
    if not flat:
        return []

    cores = cpu_count()
    label = ", ".join(sorted(p.value for p in scraped))

    if not show_dashboard:
        # Headless mode for CI / scripts.
        def _on_update(done: int, total: int) -> None:
            if done % 250 == 0 or done == total:
                console.print(f"  checked {done:,} / {total:,}", style=MUTED)
        return await check_all(
            scraped,
            concurrency=concurrency,
            timeout=timeout,
            retries=retries,
            progress_cb=_on_update,
        )

    import sys as _sys
    use_tui = _sys.stderr.isatty() and show_dashboard
    if use_tui:
        from .ui import RichTuiRunner

        runner = RichTuiRunner(
            total=len(flat),
            label=label,
            threads=concurrency,
            sources_total=sum(len(v) for v in scraped.values()),
        )
        runner.dashboard.set_phase("validating")

        # Custom check_all call with progress events feeding the TUI.
        async def check_with_events():
            from .checker import check_all as _check_all

            def on_update(done: int, _total: int) -> None:
                runner.dashboard.update(
                    checked=done,
                    working=runner.dashboard._working,
                )

            out = await _check_all(
                scraped,
                concurrency=concurrency,
                timeout=timeout,
                retries=retries,
                progress_cb=on_update,
            )
            results = list(out)
            runner.dashboard.update(
                checked=len(results),
                working=sum(1 for r in results if r.ok),
            )
            runner.dashboard.record_event("ok", f"validation complete ({len(results)} results)")
            return results

        return await runner.drive(check_with_events())

    # Plain-ASCII path (CI / piped / non-TTY capture)
    from .ui import SimpleDashboard

    dashboard = SimpleDashboard(
        total=len(flat),
        label=label,
        threads=concurrency,
    )
    dashboard.start()

    # Run check in background; dashboard reads from a shared results list
    # in the foreground loop. No Live, no cursor-up escape codes.
    results: list[CheckResult] = []

    async def run_check() -> list[CheckResult]:
        nonlocal results
        out = await check_all(
            scraped,
            concurrency=concurrency,
            timeout=timeout,
            retries=retries,
            progress_cb=None,
        )
        results = out
        return out

    task = asyncio.create_task(run_check())

    # Poll while the check runs; update the dashboard with the latest counts.
    while not task.done():
        ok_count = sum(1 for r in results if r.ok)
        dashboard.update(checked=len(results), working=ok_count)
        await asyncio.sleep(0.1)
    results = await task
    dashboard.update(checked=len(results), working=sum(1 for r in results if r.ok))

    # Apply latency filter (the checker used 2-sample; now enforce max).
    filtered = []
    for r in results:
        if not r.ok:
            continue
        if r.latency_ms > max_latency_ms:
            continue
        filtered.append(r)

    dashboard.finish(total_working=len(filtered))
    return filtered


# ---------------------------------------------------------------------------
# File mode — validate a previously scraped file.
# ---------------------------------------------------------------------------

def _parse_input_file(path: Path, types: list[Protocol]) -> dict[Protocol, set[Proxy]]:
    """Parse a plain ``ip:port`` file and assign all types to each proxy."""
    proxies = parse_file(str(path))
    if not proxies:
        console.print(f"[red]No proxies found in {path}.[/red]")
        return {}
    out: dict[Protocol, set[Proxy]] = {}
    for proto in types:
        out[proto] = set(proxies)
    return out


# ---------------------------------------------------------------------------
# Command implementations.
# ---------------------------------------------------------------------------

async def cmd_scrape(args: argparse.Namespace) -> int:
    cfg = Config.load(args.config)
    protocols = _select_protocols(args)
    out = await _do_scrape(protocols, cfg, include_extra=args.extra_sources)
    total = sum(len(v) for v in out.values())
    if total == 0:
        console.print("[red]No proxies scraped. Exiting.[/red]")
        return 1
    formats = args.output_format or ["txt"]
    written = write_all(
        (
            CheckResult(proxy=p, protocol=proto, ok=True)
            for proto, items in out.items()
            for p in items
        ),
        formats=formats,
        out_dir=args.out_dir,
    )
    console.print()
    if written:
        console.print(f"  [bold {GREEN}]Saved:[/] " + ", ".join(str(p) for p in written))
    return 0


async def cmd_check(args: argparse.Namespace) -> int:
    if not args.input_file or not args.input_file.exists():
        console.print(f"[red]Input file not found: {args.input_file}[/red]")
        return 1
    cfg = Config.load(args.config)
    protocols = _select_protocols(args)
    preset = _apply_preset(args)

    scraped = _parse_input_file(args.input_file, protocols)
    if not scraped:
        return 1

    if cfg.enrichment.anonymity or cfg.enrichment.geo or getattr(args, "enrich", False):
        results = await _do_check(scraped, preset, show_dashboard=not args.non_interactive)
        results = await enrich_results(
            results, anonymity=cfg.enrichment.anonymity, geo=cfg.enrichment.geo
        )
    else:
        results = await _do_check(scraped, preset, show_dashboard=not args.non_interactive)

    formats = args.output_format or ["txt"]
    written = write_all(results, formats=formats, out_dir=args.out_dir)
    _print_summary(results, written)
    return 0


async def cmd_run(args: argparse.Namespace) -> int:
    cfg = Config.load(args.config)
    protocols = _select_protocols(args)
    preset = _apply_preset(args)

    scraped = await _do_scrape(protocols, cfg, include_extra=args.extra_sources)
    total = sum(len(v) for v in scraped.values())
    if total == 0:
        console.print("[red]No proxies scraped. Exiting.[/red]")
        return 1

    scrape_summary = summary_table(
        "Scrape Results",
        ["Protocol", "Unique Proxies"],
        [[proto.label, f"{len(scraped.get(proto, [])):,}"] for proto in protocols]
        + [["[bold]TOTAL[/bold]", f"[bold {GREEN}]{total:,}[/]"]],
    )
    console.print(scrape_summary)
    console.print()

    if cfg.enrichment.anonymity or cfg.enrichment.geo:
        results = await _do_check(scraped, preset, show_dashboard=not args.non_interactive)
        results = await enrich_results(
            results, anonymity=cfg.enrichment.anonymity, geo=cfg.enrichment.geo
        )
    else:
        results = await _do_check(scraped, preset, show_dashboard=not args.non_interactive)

    # Target filter
    if cfg.filter.enabled and cfg.filter.targets:
        results = await _apply_target_filter(results, cfg.filter.targets, timeout=cfg.filter.timeout)

    formats = args.output_format or ["txt"]
    written = write_all(results, formats=formats, out_dir=args.out_dir)
    _print_summary(results, written)
    return 0


async def _apply_target_filter(
    results: list[CheckResult], target_names: list[str], *, timeout: float
) -> list[CheckResult]:
    sites = targets_by_names(target_names)
    if not sites:
        return results
    site_word = "site" if len(sites) == 1 else "sites"
    console.print(f"  [bold]Filtering against {len(sites)} target {site_word}.[/bold]")
    pool = [(r.proxy, r.protocol) for r in results if r.ok]
    total = len(pool) * len(sites)

    # Plain-ASCII progress so output stays clean in any terminal / log.
    progress = SimpleProgress("Filtering", total or 1, color=RED)
    progress.start()
    blocked = [0]

    def cb(done: int, _tot: int) -> None:
        progress.update(done, extra=f"{blocked[0]:,} blocked")

    passing = await filter_targets(pool, sites, concurrency=80, timeout=timeout, progress_cb=cb)
    blocked[0] = len(pool) - len(passing)
    progress.update(total, extra=f"{blocked[0]:,} blocked")
    progress.finish(
        f"{len(passing):,} of {len(pool):,} proxies survived all {len(sites)} {site_word}"
    )

    return [r for r in results if not r.ok or (r.proxy, r.protocol) in passing]


def _print_summary(results: list[CheckResult], written: list[Path]) -> None:
    ok = [r for r in results if r.ok]
    console.print()
    if ok:
        rows = []
        for proto in sorted({r.protocol for r in ok}):
            count = sum(1 for r in ok if r.protocol == proto)
            fname = f"working_{proto.label.lower()}_{date_str()}.txt"
            rows.append([proto.label, f"{count:,}", fname])
        rows.append(["[bold]TOTAL[/bold]", f"[bold {GREEN}]{len(ok):,}[/]", ""])
        console.print(summary_table("Working Proxies Summary", ["Protocol", "Working", "File"], rows))
    if written:
        console.print(f"\n  [bold {GREEN}]Saved:[/] " + ", ".join(str(p) for p in written))
    if not ok:
        console.print("[yellow]No working proxies found.[/yellow]")


def date_str() -> str:
    from datetime import date
    return date.today().isoformat()


# ---------------------------------------------------------------------------
# Entry point.
# ---------------------------------------------------------------------------

def main(argv: Sequence[str] | None = None) -> int:
    raise_fd_limit_windows()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.no_color:
        console.no_color = True

    cmd = _resolve_command(args)

    # Interactive wizard when:
    #   * the user did not pass --non-interactive
    #   * AND we're not already mid-pipeline (no input_file given)
    interactive_ok = (
        not args.non_interactive
        and not cmd == "check"  # check requires a file path
    )

    if interactive_ok:
        from .wizard import run_wizard, wizard_to_namespace

        plan = run_wizard(console, default_out_dir=args.out_dir)
        if plan.get("__quit__"):
            console.print(f"[{MUTED}]Goodbye.[/{MUTED}]")
            return 0
        # Overlay wizard choices onto the parsed args.
        args = wizard_to_namespace(plan)
        cmd = plan["action"]
        # Wizard already showed its own header — don't print the banner twice.
        args.timeout = plan["preset_values"]["timeout"]
        args.max_latency = plan["preset_values"]["max_latency_ms"]
        args.retries = plan["preset_values"]["retries"]
        args.enrich = False
    else:
        console.print()
        console.print(banner())
        console.print()

    try:
        if cmd == "scrape":
            rc = asyncio.run(cmd_scrape(args))
        elif cmd == "check":
            rc = asyncio.run(cmd_check(args))
        else:
            rc = asyncio.run(cmd_run(args))
    except KeyboardInterrupt:
        console.print("\n[red]Interrupted by user.[/red]")
        return 130
    return rc


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
