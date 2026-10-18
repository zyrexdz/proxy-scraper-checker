"""Rich-based live dashboard.

The dashboard is intentionally simple — a single progress panel with the
running metrics. The full TUI is rendered by ``cli.py``; this module is
the *panel* and *progress* primitives only.
"""

from __future__ import annotations

import asyncio
import ctypes
import sys
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable

from rich.align import Align
from rich.box import ROUNDED
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from rich.text import Text

# Theme colors (kept consistent with v2.0 for visual continuity).
GREEN = "#00e5a8"
CYAN = "#38bdf8"
MUTED = "grey62"
RED = "#f43f5e"
YELLOW = "#fbbf24"


# ---------------------------------------------------------------------------
# Cross-platform console setup.
#
# On Windows, modern terminals (Windows Terminal, conhost on Win10 1607+
# with VT enabled) support ANSI escape codes. Legacy conhost does not — and
# emit escape codes there is just visual noise. We:
#
#   1. Try to enable ENABLE_VIRTUAL_TERMINAL_PROCESSING for stdout + stderr
#      via SetConsoleMode(). On success we use Rich with ANSI colors.
#   2. On failure (very old Windows, broken ctypes, redirected stdout),
#      we use Rich's legacy Win32 console API which renders Unicode + box
#      characters via WriteConsoleW but skips ANSI codes entirely.
#
# Either way, the user sees styled output and never a wall of escape codes.
# Linux / macOS terminals universally support ANSI; auto-detection works.
# ---------------------------------------------------------------------------


def _enable_windows_vt() -> bool:
    """Best-effort: enable ENABLE_VIRTUAL_TERMINAL_PROCESSING on the
    process's stdout and stderr console handles.

    Returns ``True`` if at least the stdout handle was updated, ``False``
    if the call failed (very old Windows, redirected to a file, etc.).
    """
    if sys.platform != "win32":
        return True
    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        STD_OUTPUT_HANDLE = -11
        STD_ERROR_HANDLE = -12
        ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        updated = False
        for handle_id in (STD_OUTPUT_HANDLE, STD_ERROR_HANDLE):
            handle = kernel32.GetStdHandle(handle_id)
            if not handle or handle == ctypes.c_void_p(-1).value:
                continue
            mode = ctypes.c_uint32()
            if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                continue
            kernel32.SetConsoleMode(
                handle, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING
            )
            updated = True
        return updated
    except (OSError, AttributeError):
        return False


def _build_console() -> Console:
    """Construct the module-level :class:`Console` with the right flags."""
    if sys.platform == "win32":
        if _enable_windows_vt():
            # ANSI escape codes work now.
            return Console(legacy_windows=False, force_terminal=True)
        # Fall back to Win32 console API — no escape codes, but still
        # supports box-drawing characters and basic styling.
        return Console(legacy_windows=True)
    # Non-Windows: standard TTY handling.
    return Console()


console = _build_console()


@dataclass
class DashboardState:
    """Mutable counters the dashboard reads on every refresh tick."""

    total: int = 0
    checked: int = 0
    working: int = 0
    started_at: float = 0.0
    label: str = ""
    threads: int = 0
    cores: int = 0
    samples: deque = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.samples is None:
            self.samples = deque(maxlen=60)


def _bar(pct: float, width: int = 34) -> Text:
    filled = int(width * pct / 100)
    t = Text()
    t.append("━" * filled, style=f"bold {GREEN}")
    t.append("━" * (width - filled), style="grey30")
    return t


def _recent_hit_rate(state: DashboardState) -> float:
    if len(state.samples) < 2:
        return 0.0
    _, c_old, w_old = state.samples[0]
    _, c_new, w_new = state.samples[-1]
    dc = c_new - c_old
    dw = w_new - w_old
    return (dw / dc * 100.0) if dc > 0 else 0.0


def build_panel(state: DashboardState) -> Panel:
    pct = (state.checked / state.total * 100) if state.total else 0.0
    elapsed = max(time.time() - state.started_at, 1e-6)
    cpm = state.checked / elapsed * 60.0
    hit = (state.working / state.checked * 100) if state.checked else 0.0

    prog = Table.grid(padding=(0, 1))
    prog.add_column()
    prog.add_column(justify="right", style=f"bold {GREEN}")
    prog.add_row(_bar(pct), f"{pct:5.1f}%")

    counts = Text()
    counts.append(f"{state.checked:,}", style="bold white")
    counts.append(f" / {state.total:,} checked", style=MUTED)

    metrics = Table.grid(padding=(0, 3), expand=True)
    for _ in range(5):
        metrics.add_column(justify="center")

    def cell(label: str, val: str, color: str) -> Text:
        c = Text(justify="center")
        c.append(val + "\n", style=f"bold {color}")
        c.append(label, style=MUTED)
        return c

    metrics.add_row(
        cell("WORKING", f"{state.working:,}", GREEN),
        cell("HIT RATE (avg)", f"{hit:.1f}%", CYAN),
        cell("HIT RATE (recent)", f"{_recent_hit_rate(state):.1f}%", CYAN),
        cell("CPM", f"{cpm:,.0f}", YELLOW),
        cell("ELAPSED", f"{elapsed:,.0f}s", "white"),
    )

    cfg = Text()
    cfg.append("  type ", style=MUTED)
    cfg.append(state.label, style="white")
    cfg.append("    cores ", style=MUTED)
    cfg.append(str(state.cores), style="white")
    cfg.append("    threads ", style=MUTED)
    cfg.append(f"{state.threads}", style="white")

    body = Group(
        cfg,
        Text(""),
        prog,
        Align.right(counts),
        Text(""),
        metrics,
    )
    return Panel(
        body,
        title=f"[bold {GREEN}]Validating Proxies[/]",
        subtitle=f"[{MUTED}]zyre-proxy-scraper v3[/]",
        border_style=GREEN,
        box=ROUNDED,
        padding=(1, 3),
    )


def scrape_progress(total: int) -> Progress:
    """Progress bar used during the scrape phase.

    Kept for users on real TTYs; the default flow uses ``SimpleProgress``
    which renders one line per update and works in any terminal, including
    non-TTY captures (CI logs, file redirects, etc.).
    """
    return Progress(
        SpinnerColumn(style=GREEN),
        TextColumn(f"[bold {GREEN}]Fetching sources[/]"),
        BarColumn(complete_style=GREEN, finished_style=GREEN, pulse_style=CYAN),
        TaskProgressColumn(),
        TextColumn("[bold white]{task.fields[found]:,}[/] [grey62]proxies[/]"),
        TimeElapsedColumn(),
        console=console,
    )


def filter_progress(total: int) -> Progress:
    return Progress(
        SpinnerColumn(style=RED),
        TextColumn(f"[bold {RED}]Filtering targets[/]"),
        BarColumn(complete_style=RED, finished_style=RED, pulse_style="#fb7185"),
        TaskProgressColumn(),
        TextColumn("[bold white]{task.fields[blocked]:,}[/] [grey62]blocked[/]"),
        TimeElapsedColumn(),
        console=console,
    )


# ---------------------------------------------------------------------------
# Simple progress — the default.
#
# Rich's `Live` / `Progress` rely on ANSI escape codes (cursor-up, erase-line)
# to redraw in place. That works on a real TTY, but produces a wall of
# garbage escape codes when stdout is piped, redirected to a log, or printed
# through a terminal that doesn't process ANSI.
#
# This class prints one line per update, throttled to ~5 lines per second,
# and always ends with a clean final summary line. It is the default for the
# CLI; switch to the rich TUI mode with ``--tui``.
# ---------------------------------------------------------------------------


class SimpleProgress:
    """Throttled line-based progress reporter.

    Renders one of two ways, chosen automatically:

    * **TTY** (real terminal): overwrite a single line in place using ``\\r``.
    * **Non-TTY** (piped, captured to a log, redirected to a file): one
      line per update so the output is readable in any tool.

    Usage::

        p = SimpleProgress("Scraping", total=150)
        p.start()
        for i in range(150):
            do_work()
            p.update(i + 1, extra="252,385 proxies")
        p.finish("Done — 150 sources scraped, 252,385 proxies")
    """

    def __init__(self, label: str, total: int, *, color: str = GREEN) -> None:
        self.label = label
        self.total = total
        self.color = color
        self._done = 0
        self._last_print = 0.0
        self._start_ts = 0.0
        self._min_interval = 0.2  # 5 updates/sec
        self._finished = False
        import sys as _sys
        self._tty = _sys.stderr.isatty()
        self._last_len = 0

    def start(self) -> None:
        import time as _t
        self._start_ts = _t.time()
        self._print_line(0, "", force=True)

    def update(self, done: int, *, extra: str = "") -> None:
        import time as _t
        self._done = done
        now = _t.time()
        if now - self._last_print < self._min_interval and done < self.total:
            return
        self._last_print = now
        self._print_line(done, extra, force=False)

    def _print_line(self, done: int, extra: str, *, force: bool) -> None:
        import time as _t, sys as _sys
        pct = (done / self.total * 100) if self.total else 0.0
        elapsed = _t.time() - self._start_ts if self._start_ts else 0.0
        bar = self._ascii_bar(pct)
        extra_str = f"  {extra}" if extra else ""
        line = f"  {bar} {pct:5.1f}%  {done:,}/{self.total:,}  {elapsed:5.1f}s{extra_str}"
        if self._tty:
            # Overwrite the previous line in place.
            pad = max(0, self._last_len - len(line))
            _sys.stderr.write("\r" + line + " " * pad)
            _sys.stderr.flush()
            self._last_len = len(line)
        else:
            # One full line per update — readable in any log.
            _sys.stderr.write(line + "\n")
            _sys.stderr.flush()

    def _ascii_bar(self, pct: float) -> str:
        filled = int(30 * pct / 100)
        return "[" + "=" * filled + " " * (30 - filled) + "]"

    def finish(self, summary: str) -> None:
        if self._finished:
            return
        self._finished = True
        import sys as _sys, time as _t
        elapsed = _t.time() - self._start_ts if self._start_ts else 0.0
        if self._tty:
            # Clear the live line, then print a clean one.
            _sys.stderr.write("\r" + " " * self._last_len + "\r")
        _sys.stderr.write(
            f"  [done] {self.label} complete - {self._done:,}/{self.total:,} "
            f"in {elapsed:.1f}s\n"
        )
        _sys.stderr.flush()
        # Summary on stdout so it survives a `2>&1` redirect.
        console.print(f"  [bold {self.color}]{summary}[/]")


def _bar(pct: float, width: int = 30) -> str:
    """Plain-ASCII progress bar (no Unicode, no escape codes)."""
    filled = int(width * pct / 100)
    return "[" + "=" * filled + " " * (width - filled) + "]"


# ---------------------------------------------------------------------------
# Rich TUI dashboard — the new hotness.
#
# A multi-region Live display with:
#   - Header:   project title, current phase, elapsed clock
#   - Body:     left = progress bar + current source; right = live stats
#   - Footer:   recent events (sources that succeeded / failed)
#
# This is the default dashboard on TTY-capable terminals. On non-TTY
# (piped / redirected) the SimpleDashboard / SimpleProgress classes are
# used instead because Layout uses ANSI box drawing which doesn't always
# survive capture.
# ---------------------------------------------------------------------------


class RichTUIDashboard:
    """Multi-region Live dashboard for the checker phase."""

    def __init__(
        self,
        total: int,
        label: str,
        threads: int,
        sources_total: int = 0,
    ) -> None:
        self.total = total
        self.label = label
        self.threads = threads
        self.sources_total = sources_total
        self._started_at = time.time()
        self._checked = 0
        self._working = 0
        self._samples: list[tuple[float, int, int]] = []
        self._events: deque[tuple[str, str, str]] = deque(maxlen=8)
        self._phase = "scrape"

    def set_phase(self, phase: str) -> None:
        self._phase = phase
        self._events.append(("phase", phase, time.strftime("%H:%M:%S")))

    def record_event(self, kind: str, msg: str) -> None:
        self._events.append((kind, msg, time.strftime("%H:%M:%S")))

    def update(self, checked: int, working: int) -> None:
        self._checked = checked
        self._working = working
        self._samples.append((time.time(), checked, working))
        if len(self._samples) > 120:
            self._samples = self._samples[-120:]

    def _hit_avg(self) -> float:
        return (self._working / self._checked * 100) if self._checked else 0.0

    def _hit_recent(self) -> float:
        if len(self._samples) < 2:
            return 0.0
        _, c_old, w_old = self._samples[0]
        _, c_new, w_new = self._samples[-1]
        dc = c_new - c_old
        dw = w_new - w_old
        return (dw / dc * 100.0) if dc > 0 else 0.0

    def render(self) -> "Layout":  # type: ignore[name-defined]
        from rich.layout import Layout

        pct = (self._checked / self.total * 100) if self.total else 0.0
        elapsed = max(time.time() - self._started_at, 1e-6)
        cpm = self._checked / elapsed * 60.0
        hit = self._hit_avg()
        recent = self._hit_recent()

        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="body"),
            Layout(name="footer", size=8),
        )
        layout["body"].split_row(
            Layout(name="left"),
            Layout(name="right", size=38),
        )

        # Header — title + clocks
        title = Text()
        title.append(" ZYRE ", style=f"bold {GREEN}")
        title.append(f"{self._phase.upper()}", style=f"bold {CYAN}")
        title.append("    ")
        title.append(self.label, style="bold white")
        title.append("    ")
        title.append(f"{cpm:,.0f} cpm", style=YELLOW)
        layout["header"].update(
            Panel(title, box=ROUNDED, border_style=GREEN, padding=(0, 2))
        )

        # Left body: progress bar + counters
        from rich.align import Align
        from rich.console import Group
        bar_text = Text()
        bar_text.append(_bar(pct, width=46), style=f"bold {GREEN}")
        bar_text.append(f"  {pct:5.1f}%", style="bold white")
        lines = Text.from_markup(
            f"  [bold white]{self._checked:,}[/] of [bold white]{self.total:,}[/] checked"
            f"\n\n  working: [bold {GREEN}]{self._working:,}[/]   "
            f"hit: [bold {CYAN}]{hit:.1f}%[/]   "
            f"recent: [bold {CYAN}]{recent:.1f}%[/]"
        )
        left_group = Group(
            Align.left(bar_text),
            Text(""),
            lines,
            Text(""),
            Text.from_markup(
                f"  [{MUTED}]sources: {self.sources_total}   "
                f"threads: {self.threads}   "
                f"target samples: {len(self._samples)}[/]",
            ),
        )
        layout["left"].update(
            Panel(left_group, box=ROUNDED, border_style=MUTED, title="[bold]Check loop[/]")
        )

        # Right body: stats table
        from rich.table import Table
        stats = Table(
            box=ROUNDED,
            border_style=GREEN,
            title="[bold white]Live stats[/]",
            title_justify="left",
            padding=(0, 1),
        )
        stats.add_column("Metric", style=MUTED)
        stats.add_column("Value", justify="right", style="bold white")
        stats.add_row("Working",      f"{self._working:,}")
        stats.add_row("Hit (avg)",    f"{hit:.1f}%")
        stats.add_row("Hit (recent)", f"{recent:.1f}%")
        stats.add_row("CPM",          f"{cpm:,.0f}")
        stats.add_row("Progress",     f"{pct:.1f}%")
        stats.add_row("Elapsed",      f"{elapsed:,.0f}s")
        layout["right"].update(stats)

        # Footer: recent events
        ev_rows = []
        for kind, msg, ts in list(self._events)[-6:]:
            color = GREEN if kind == "ok" else (RED if kind == "fail" else CYAN)
            sym = "+" if kind == "ok" else ("x" if kind == "fail" else "*")
            ev_rows.append(f"  [{color}]{sym}[/{color}] [{MUTED}]{ts}[/{MUTED}]  {msg}")
        if not ev_rows:
            ev_rows = [f"  [{MUTED}]waiting for events...[/{MUTED}]"]
        ev_text = Text.from_markup("\n".join(ev_rows))
        layout["footer"].update(
            Panel(
                ev_text,
                box=ROUNDED,
                border_style=MUTED,
                title="[bold]Events[/]",
                padding=(0, 1),
            )
        )
        return layout


# ---------------------------------------------------------------------------
# TUI mode using Live + Layout. Only used when stderr is a TTY.
# ---------------------------------------------------------------------------


class RichTuiRunner:
    """Run the checker in a background task while showing a Live TUI."""

    def __init__(
        self,
        total: int,
        label: str,
        threads: int,
        sources_total: int = 0,
    ) -> None:
        self.dashboard = RichTUIDashboard(
            total=total,
            label=label,
            threads=threads,
            sources_total=sources_total,
        )

    async def drive(self, check_coro) -> list:
        """Run ``check_coro`` (an awaitable) while driving the Live display."""
        from rich.live import Live

        async def runner() -> list:
            results = await check_coro
            return list(results)

        task = asyncio.create_task(runner())
        with Live(self.dashboard.render(), console=console, refresh_per_second=8) as live:
            while not task.done():
                await asyncio.sleep(0.1)
                live.update(self.dashboard.render())
            results = await task
            live.update(self.dashboard.render())
        return results


class SimpleDashboard:
    """Plain-text checker dashboard — the replacement for the Rich Live panel.

    The old `Live(build_panel(state))` rendered beautifully in a real TTY but
    emitted a wall of cursor-up / erase-line escape codes when stdout was
    piped or captured. This class writes one line at a time, overwrites it
    with ``\\r`` on each tick, and prints a clean final summary.
    """

    def __init__(self, total: int, label: str, threads: int) -> None:
        self.total = total
        self.label = label
        self.threads = threads
        self._checked = 0
        self._working = 0
        self._start = 0.0
        self._last_print = 0.0
        self._min_interval = 0.2
        self._samples: list[tuple[float, int, int]] = []
        self._done = False
        import sys as _sys
        self._tty = _sys.stderr.isatty()
        self._last_len = 0

    def start(self) -> None:
        import time as _t
        self._start = _t.time()
        self._last_print = self._start
        self._print(force=True)

    def update(self, checked: int, working: int) -> None:
        import time as _t
        self._checked = checked
        self._working = working
        self._samples.append((_t.time(), checked, working))
        if len(self._samples) > 60:
            self._samples = self._samples[-60:]
        if _t.time() - self._last_print < self._min_interval and checked < self.total:
            return
        self._last_print = _t.time()
        self._print(force=False)

    def _print(self, *, force: bool) -> None:
        import sys as _sys, time as _t
        pct = (self._checked / self.total * 100) if self.total else 0.0
        elapsed = _t.time() - self._start if self._start else 0.0
        cpm = self._checked / max(elapsed, 1e-6) * 60.0
        hit = (self._working / self._checked * 100) if self._checked else 0.0
        recent = self._recent_hit_rate()
        line = (
            f"  {self._ascii_bar(pct)} {pct:5.1f}%  "
            f"{self._checked:,}/{self.total:,}  "
            f"working={self._working:,}  "
            f"hit={hit:.1f}%  recent={recent:.1f}%  "
            f"cpm={cpm:,.0f}  {elapsed:5.1f}s"
        )
        if self._tty:
            pad = max(0, self._last_len - len(line))
            _sys.stderr.write("\r" + line + " " * pad)
            _sys.stderr.flush()
            self._last_len = len(line)
        else:
            _sys.stderr.write(line + "\n")
            _sys.stderr.flush()

    def _ascii_bar(self, pct: float) -> str:
        filled = int(30 * pct / 100)
        return "[" + "=" * filled + " " * (30 - filled) + "]"

    def _recent_hit_rate(self) -> float:
        if len(self._samples) < 2:
            return 0.0
        _, c_old, w_old = self._samples[0]
        _, c_new, w_new = self._samples[-1]
        dc = c_new - c_old
        dw = w_new - w_old
        return (dw / dc * 100.0) if dc > 0 else 0.0

    def finish(self, total_working: int) -> None:
        if self._done:
            return
        self._done = True
        import sys as _sys, time as _t
        elapsed = _t.time() - self._start if self._start else 0.0
        if self._tty:
            _sys.stderr.write("\r" + " " * self._last_len + "\r")
        _sys.stderr.write(
            f"  [done] Validation complete - {total_working:,} working "
            f"of {self.total:,} in {elapsed:.1f}s\n"
        )
        _sys.stderr.flush()


def banner() -> Panel:
    from .sources import ALL_SOURCES

    total = len(ALL_SOURCES)
    sub = Text()
    sub.append("* ", style=f"bold {GREEN}")
    sub.append(f"{total} APIs", style="bold white")
    sub.append("   |   ", style=MUTED)
    sub.append("HTTP / SOCKS4 / SOCKS5", style="white")
    sub.append("   |   ", style=MUTED)
    sub.append("async I/O + multi-judge", style=f"bold {CYAN}")
    return Panel(
        sub,
        border_style=GREEN,
        title=f"[bold {GREEN}]ZYRE PROXY SCRAPER[/] [{MUTED}]& CHECKER[/]",
        subtitle=f"[{MUTED}]v3[/]",
        padding=(1, 3),
        box=ROUNDED,
    )


def summary_table(title: str, headers: list[str], rows: list[list[str]]) -> Table:
    table = Table(
        box=ROUNDED,
        border_style=MUTED,
        header_style=f"bold {GREEN}",
        title=f"[bold white]{title}[/]",
        title_justify="left",
        expand=False,
        padding=(0, 2),
    )
    for h in headers:
        table.add_column(h, style="bold white")
    for row in rows:
        table.add_row(*row)
    return table
