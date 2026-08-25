from __future__ import annotations

import concurrent.futures
import json
import multiprocessing as mp
import os
import platform
import queue as tqueue
import random
import re
import sys
import threading
import time
import warnings
from collections import defaultdict, deque
from datetime import date
from pathlib import Path

warnings.filterwarnings("ignore", message=".*urllib3.*")
warnings.filterwarnings("ignore", category=UserWarning)

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

import requests
from requests.adapters import HTTPAdapter
from rich import box
from rich.align import Align
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
from rich.prompt import FloatPrompt, IntPrompt, Prompt
from rich.table import Table
from rich.text import Text

from sources import SOURCES

console = Console(legacy_windows=False)

green = "#00e5a8"
cyan = "#38bdf8"
muted = "grey62"
red = "#f43f5e"
yellow = "#fbbf24"

_ip_port_re = re.compile(r"((?:\d{1,3}\.){3}\d{1,3}):(\d{2,5})")
_global_ip_re = re.compile(
    r"(?P<ip>(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.(?:25[0-5]|2[0-4]\d|[01]?\d\d?))[^\d]+(?P<port>\d{2,5})",
    flags=re.IGNORECASE,
)

try:
    import socks

    socks_supported = True
except ImportError:
    socks_supported = False


def _match_protocol(item: dict, expected: str) -> bool:
    target = expected.lower().replace(" ", "")
    if "protocol" in item:
        p = str(item["protocol"]).lower().replace(" ", "")
        return target in p or p in target
    if "protocols" in item and isinstance(item["protocols"], list):
        return any(target in str(p).lower() or str(p).lower() in target for p in item["protocols"])
    return True


def parse_proxies(text: str, expected: str = "") -> set[tuple[str, str, str, str]]:
    proxies: set[tuple[str, str, str, str]] = set()

    try:
        payload = json.loads(text)
        items = payload.get("data", []) if isinstance(payload, dict) else (payload if isinstance(payload, list) else [])
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict) or "ip" not in item or "port" not in item:
                    continue
                if expected and not _match_protocol(item, expected):
                    continue
                proxies.add((str(item["ip"]), str(item["port"]), "", ""))
            if proxies:
                return proxies
    except (json.JSONDecodeError, TypeError, ValueError):
        pass

    for word in text.split():
        clean = word.strip("""'",[](){}""")
        match = _ip_port_re.search(clean)
        if not match:
            continue

        ip, port = match.groups()
        if not (0 < int(port) <= 65535):
            continue

        user, passwd = "", ""
        remainder = clean.replace(f"{ip}:{port}", "", 1).strip(":@")
        if ":" in remainder:
            parts = remainder.split(":", 1)
            if len(parts) == 2:
                user, passwd = parts

        proxies.add((ip, port, user, passwd))

    seen = {(p[0], p[1]) for p in proxies}
    for ip, port in _global_ip_re.findall(text):
        if port and 0 < int(port) <= 65535 and (ip, port) not in seen:
            proxies.add((ip, port, "", ""))
            seen.add((ip, port))

    return proxies


def fetch_source(url: str, proto: str, session: requests.Session, timeout: int = 15) -> set[tuple[str, str, str, str]]:
    agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
    ]
    try:
        resp = session.get(url, timeout=timeout, headers={"User-Agent": random.choice(agents)})
        if resp.status_code == 200 and resp.text:
            return parse_proxies(resp.text, proto)
    except Exception:
        pass
    return set()


def scrape(types: list[str]) -> dict[str, set[tuple[str, str, str, str]]]:
    jobs: list[tuple[str, str]] = []
    for proto in types:
        for url in SOURCES.get(proto, []):
            jobs.append((proto, url))

    results: dict[str, set[tuple[str, str, str, str]]] = defaultdict(set)
    lock = threading.Lock()

    progress = Progress(
        SpinnerColumn(style=green),
        TextColumn(f"[bold {green}]Fetching sources[/]"),
        BarColumn(complete_style=green, finished_style=green, pulse_style=cyan),
        TaskProgressColumn(),
        TextColumn("[bold white]{task.fields[found]:,}[/] [grey62]proxies[/]"),
        TimeElapsedColumn(),
        console=console,
    )

    found = 0
    with progress:
        task = progress.add_task("scrape", total=len(jobs), found=0)
        session = requests.Session()
        adapter = HTTPAdapter(pool_connections=50, pool_maxsize=50, max_retries=1)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        def worker(job: tuple[str, str]) -> None:
            nonlocal found
            proto, url = job
            got = fetch_source(url, proto, session)
            with lock:
                results[proto].update(got)
                found += len(got)
                progress.update(task, advance=1, found=found)

        with concurrent.futures.ThreadPoolExecutor(max_workers=50) as ex:
            list(ex.map(worker, jobs))

    return results


_local = threading.local()


def _get_session() -> requests.Session:
    try:
        return _local.session
    except AttributeError:
        session = requests.Session()
        adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20, max_retries=0)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Connection": "close",
            }
        )
        _local.session = session
        return session


def _raise_fd_limit() -> None:
    try:
        import resource

        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        target = min(65536, hard) if hard > 0 else 65536
        if soft < target:
            resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))
    except Exception:
        pass


def check_proxy(
    session: requests.Session,
    proxy: tuple[str, str, str, str],
    proto: str,
    timeout: float = 8.0,
    retries: int = 3,
) -> float:
    ip, port, user, passwd = proxy
    auth = f"{user}:{passwd}@" if user and passwd else ""
    addr = f"{auth}{ip}:{port}"

    if proto in ("http", "https"):
        url = f"http://{addr}"
    elif proto == "socks5":
        url = f"socks5h://{addr}"
    elif proto == "socks4":
        url = f"socks4://{addr}"
    else:
        url = f"{proto}://{addr}"

    proxies = {"http": url, "https": url}
    connect_timeout = min(3.5, timeout)
    read_timeout = timeout

    judges = (
        ("http://checkip.amazonaws.com", "."),
        ("http://api.ipify.org", "."),
        ("https://api.ipify.org", "."),
    )

    for attempt in range(max(1, retries)):
        judge_url, marker = judges[attempt % len(judges)]
        try:
            start = time.time()
            resp = session.get(judge_url, proxies=proxies, timeout=(connect_timeout, read_timeout))
            elapsed = (time.time() - start) * 1000.0
            if resp.status_code == 200 and (not marker or marker in resp.text):
                return elapsed
        except Exception:
            pass
    return -1.0


def _proc_worker(
    chunk: list[tuple[tuple[str, str, str, str], str]],
    threads: int,
    timeout: float,
    max_speed: float,
    retries: int,
    checked,
    working,
    results,
) -> None:
    q: tqueue.Queue[tuple[tuple[str, str, str, str], str]] = tqueue.Queue()
    for item in chunk:
        q.put(item)

    def thread_body() -> None:
        session = _get_session()
        while True:
            try:
                proxy, proto = q.get_nowait()
            except tqueue.Empty:
                return

            elapsed = check_proxy(session, proxy, proto, timeout, retries)
            with checked.get_lock():
                checked.value += 1

            if 0 <= elapsed <= max_speed:
                with working.get_lock():
                    working.value += 1
                results.put((proto, proxy))

    workers = [threading.Thread(target=thread_body, daemon=True) for _ in range(max(1, threads))]
    for t in workers:
        t.start()
    for t in workers:
        t.join()


def _bar(pct: float, width: int = 34) -> Text:
    filled = int(width * pct / 100)
    t = Text()
    t.append("━" * filled, style=f"bold {green}")
    t.append("━" * (width - filled), style="grey30")
    return t


def build_dashboard(
    checked: int,
    working: int,
    total: int,
    elapsed: float,
    proto_label: str,
    threads: int,
    cores: int,
    recent_hit: float = 0.0,
) -> Panel:
    pct = (checked / total * 100) if total else 0.0
    cpm = checked / max(elapsed, 1e-6) * 60.0
    hit = (working / checked * 100) if checked else 0.0

    prog = Table.grid(padding=(0, 1))
    prog.add_column()
    prog.add_column(justify="right", style=f"bold {green}")
    prog.add_row(_bar(pct), f"{pct:5.1f}%")

    counts = Text()
    counts.append(f"{checked:,}", style="bold white")
    counts.append(f" / {total:,} checked", style=muted)

    metrics = Table.grid(padding=(0, 3), expand=True)
    for _ in range(5):
        metrics.add_column(justify="center")

    def cell(label: str, val: str, color: str) -> Text:
        c = Text(justify="center")
        c.append(val + "\n", style=f"bold {color}")
        c.append(label, style=muted)
        return c

    metrics.add_row(
        cell("WORKING", f"{working:,}", green),
        cell("HIT RATE (avg)", f"{hit:.1f}%", cyan),
        cell("HIT RATE (recent)", f"{recent_hit:.1f}%", cyan),
        cell("CPM", f"{cpm:,.0f}", yellow),
        cell("ELAPSED", f"{elapsed:,.0f}s", "white"),
    )

    cfg = Text()
    cfg.append("  type ", style=muted)
    cfg.append(proto_label, style="white")
    cfg.append("    cores ", style=muted)
    cfg.append(str(cores), style="white")
    cfg.append("    threads ", style=muted)
    cfg.append(f"{threads} ({threads // cores}/core)", style="white")

    group = Group(
        cfg,
        Text(""),
        prog,
        Align.right(counts),
        Text(""),
        metrics,
    )
    return Panel(
        group,
        title=f"[bold {green}]Validating Proxies[/]",
        subtitle=f"[{muted}]zyre-proxy-scraper v2.0[/]",
        border_style=green,
        box=box.ROUNDED,
        padding=(1, 3),
    )


def validate(
    proxies: dict[str, set[tuple[str, str, str, str]]],
    threads: int,
    combined: bool,
    timeout: float = 8.0,
    max_speed: float = 5000.0,
    retries: int = 3,
) -> dict[str, list[str]]:
    _raise_fd_limit()

    today = date.today().isoformat()
    if combined:
        try:
            os.remove(f"working_all_{today}.txt")
        except FileNotFoundError:
            pass
    else:
        for proto in proxies.keys():
            try:
                os.remove(f"working_{proto}_{today}.txt")
            except FileNotFoundError:
                pass

    work: list[tuple[tuple[str, str, str, str], str]] = []
    for proto, items in proxies.items():
        for p in items:
            work.append((p, proto))
    random.shuffle(work)

    total = len(work)
    working: dict[str, list[str]] = defaultdict(list)
    proto_label = ", ".join(sorted(proxies.keys()))

    cores = max(1, os.cpu_count() or 1)
    cores = min(cores, total) if total else 1
    threads_per_core = max(1, threads // cores)

    chunks: list[list[tuple[tuple[str, str, str, str], str]]] = [[] for _ in range(cores)]
    for i, item in enumerate(work):
        chunks[i % cores].append(item)

    checked = mp.Value("i", 0)
    working_count = mp.Value("i", 0)
    results: mp.Queue = mp.Queue()

    procs = [
        mp.Process(
            target=_proc_worker,
            args=(
                chunk,
                threads_per_core,
                timeout,
                max_speed,
                retries,
                checked,
                working_count,
                results,
            ),
            daemon=True,
        )
        for chunk in chunks
        if chunk
    ]

    start = time.time()
    for p in procs:
        p.start()

    def drain() -> None:
        while True:
            try:
                proto, proxy = results.get_nowait()
            except tqueue.Empty:
                return

            auth = f"{proxy[2]}:{proxy[3]}@" if proxy[2] and proxy[3] else ""
            addr = f"{auth}{proxy[0]}:{proxy[1]}"
            working[proto].append(addr)

            fname = f"working_all_{today}.txt" if combined else f"working_{proto}_{today}.txt"
            with open(fname, "a", encoding="utf-8") as fh:
                fh.write(addr + "\n")

    samples: deque = deque(maxlen=60)

    def recent_hit_rate() -> float:
        if len(samples) < 2:
            return 0.0
        _, c_old, w_old = samples[0]
        _, c_new, w_new = samples[-1]
        dc = c_new - c_old
        dw = w_new - w_old
        return (dw / dc * 100.0) if dc > 0 else 0.0

    with Live(
        build_dashboard(0, 0, total, 0.0, proto_label, threads, cores),
        console=console,
        refresh_per_second=8,
    ) as live:
        while any(p.is_alive() for p in procs):
            drain()
            samples.append((time.time(), checked.value, working_count.value))
            live.update(
                build_dashboard(
                    checked.value,
                    working_count.value,
                    total,
                    time.time() - start,
                    proto_label,
                    threads,
                    cores,
                    recent_hit_rate(),
                )
            )
            time.sleep(0.1)

        time.sleep(0.2)
        drain()
        live.update(
            build_dashboard(
                checked.value,
                working_count.value,
                total,
                time.time() - start,
                proto_label,
                threads,
                cores,
                recent_hit_rate(),
            )
        )

    for p in procs:
        p.join()
    drain()

    return working


def test_site(
    proxy: str,
    proto: str,
    url: str,
    expected_status: int = 200,
    timeout: float = 8.0,
) -> bool:
    if proto in ("http", "https"):
        proxy_url = f"http://{proxy}"
    elif proto == "socks5":
        proxy_url = f"socks5h://{proxy}"
    elif proto == "socks4":
        proxy_url = f"socks4://{proxy}"
    else:
        proxy_url = f"{proto}://{proxy}"

    proxies = {"http": proxy_url, "https": proxy_url}
    try:
        resp = requests.get(
            url,
            proxies=proxies,
            timeout=(4.0, timeout),
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            allow_redirects=True,
        )
        if resp.status_code in (403, 429, 503):
            return False
        return resp.status_code == expected_status or (200 <= resp.status_code < 400)
    except Exception:
        return False


def pick_targets() -> tuple[bool, list[str]]:
    targets = {
        "Twitch": ("https://www.twitch.tv/", 200),
        "Discord": ("https://discord.com/", 200),
        "Steam": ("https://store.steampowered.com/", 200),
        "Cloudflare": ("https://cloudflare.com/", 200),
        "Google": ("https://www.google.com/", 200),
        "Netflix": ("https://www.netflix.com/", 200),
        "Amazon": ("https://www.amazon.com/", 200),
        "Instagram": ("https://www.instagram.com/", 200),
        "Twitter/X": ("https://x.com/", 200),
        "Spotify": ("https://www.spotify.com/", 200),
        "Riot Games": ("https://www.riotgames.com/", 200),
        "Epic Games": ("https://www.epicgames.com/", 200),
    }

    console.print()
    table = Table(
        box=box.ROUNDED,
        border_style=muted,
        header_style=f"bold {green}",
        title="[bold white]Target Ban Filter[/]",
        title_justify="left",
        expand=False,
        padding=(0, 2),
    )
    table.add_column("#", justify="center", style=f"bold {cyan}")
    table.add_column("Option", style="bold white")
    table.add_column("Description", style=muted)

    table.add_row("1", "Skip filter", "Keep all validated proxies")
    table.add_row("2", "Quick Check", "Test against Twitch, Discord, Google, Cloudflare")
    table.add_row("3", "Full Check", "Test against all 12 major platforms")
    table.add_row("4", "Custom selection", "Pick specific targets to test")
    console.print(table)

    choice = Prompt.ask(
        f"[bold {green}]>[/] [bold]Choice[/bold]",
        choices=["1", "2", "3", "4"],
        default="1",
    )

    if choice == "1":
        return False, []
    if choice == "2":
        return True, ["Twitch", "Discord", "Google", "Cloudflare"]
    if choice == "3":
        return True, list(targets.keys())

    console.print()
    site_table = Table(
        box=box.ROUNDED,
        border_style=muted,
        header_style=f"bold {green}",
        title="[bold white]Available Targets[/]",
        title_justify="left",
        expand=False,
        padding=(0, 2),
    )
    site_table.add_column("#", justify="center", style=f"bold {cyan}")
    site_table.add_column("Service", style="bold white")
    site_table.add_column("URL", style=muted)

    keys = list(targets.keys())
    for i, name in enumerate(keys, 1):
        url, _ = targets[name]
        site_table.add_row(str(i), name, url)
    console.print(site_table)

    raw = Prompt.ask(
        f"[bold {green}]>[/] [bold]Enter numbers separated by commas (e.g. 1,2,4)[/bold]",
        default="1,2,4",
    )
    selected = []
    for part in raw.split(","):
        clean_part = part.strip()
        if clean_part.isdigit():
            idx = int(clean_part) - 1
            if 0 <= idx < len(keys):
                selected.append(keys[idx])

    if not selected:
        selected = ["Twitch", "Discord", "Google", "Cloudflare"]
    return True, selected


def filter_targets(
    working: dict[str, list[str]],
    sites: list[str],
    timeout: float = 8.0,
) -> dict[str, list[str]]:
    targets = {
        "Twitch": ("https://www.twitch.tv/", 200),
        "Discord": ("https://discord.com/", 200),
        "Steam": ("https://store.steampowered.com/", 200),
        "Cloudflare": ("https://cloudflare.com/", 200),
        "Google": ("https://www.google.com/", 200),
        "Netflix": ("https://www.netflix.com/", 200),
        "Amazon": ("https://www.amazon.com/", 200),
        "Instagram": ("https://www.instagram.com/", 200),
        "Twitter/X": ("https://x.com/", 200),
        "Spotify": ("https://www.spotify.com/", 200),
        "Riot Games": ("https://www.riotgames.com/", 200),
        "Epic Games": ("https://www.epicgames.com/", 200),
    }

    all_proxies: list[tuple[str, str]] = []
    for proto, addrs in working.items():
        for addr in addrs:
            all_proxies.append((proto, addr))

    total = len(all_proxies) * len(sites)
    blacklisted: dict[str, set[str]] = defaultdict(set)
    lock = threading.Lock()

    progress = Progress(
        SpinnerColumn(style=red),
        TextColumn(f"[bold {red}]Filtering targets[/]"),
        BarColumn(complete_style=red, finished_style=red, pulse_style="#fb7185"),
        TaskProgressColumn(),
        TextColumn("[bold white]{task.fields[blocked]:,}[/] [grey62]blocked[/]"),
        TimeElapsedColumn(),
        console=console,
    )

    blocked = 0
    with progress:
        task = progress.add_task("filter", total=total, blocked=0)

        def worker(item: tuple[str, str, str, str, int]) -> None:
            nonlocal blocked
            proto, addr, site_name, url, expected = item
            clean = test_site(addr, proto, url, expected, timeout)
            with lock:
                if not clean:
                    blacklisted[site_name].add(addr)
                    blocked += 1
                progress.update(task, advance=1, blocked=blocked)

        jobs = []
        for proto, addr in all_proxies:
            for site_name in sites:
                url, expected = targets[site_name]
                jobs.append((proto, addr, site_name, url, expected))

        max_workers = min(200, len(jobs)) if jobs else 1
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
            list(ex.map(worker, jobs))

    console.print()
    result_table = Table(
        box=box.ROUNDED,
        border_style=muted,
        header_style=f"bold {green}",
        title="[bold white]Target Filter Summary[/]",
        title_justify="left",
        expand=False,
        padding=(0, 2),
    )
    result_table.add_column("Target", style="bold white")
    result_table.add_column("Blocked", justify="right", style=red)
    result_table.add_column("Status", style=muted)

    all_blocked: set[str] = set()
    for site_name in sites:
        blocked_set = blacklisted.get(site_name, set())
        all_blocked.update(blocked_set)
        count = len(blocked_set)
        status = "Clean" if not count else f"{count} proxies flagged"
        result_table.add_row(site_name, f"{count:,}", status)

    result_table.add_section()
    result_table.add_row(
        "[bold]TOTAL UNIQUE BLOCKED[/bold]",
        f"[bold {red}]{len(all_blocked):,}[/]",
        "",
    )
    console.print(result_table)

    filtered: dict[str, list[str]] = defaultdict(list)
    removed = 0
    for proto, addrs in working.items():
        for addr in addrs:
            if addr in all_blocked:
                removed += 1
            else:
                filtered[proto].append(addr)

    total_before = sum(len(v) for v in working.values())
    total_after = sum(len(v) for v in filtered.values())
    console.print(
        f"\n  [bold white]{total_before:,}[/] proxies before filter -> "
        f"[bold {green}]{total_after:,}[/] clean proxies after filter "
        f"([bold {red}]-{removed:,}[/] removed)"
    )

    return filtered


def save(working: dict[str, list[str]], combined: bool = False) -> list[str]:
    today = date.today().isoformat()
    written: list[str] = []

    if combined:
        all_proxies = []
        for proxies in working.values():
            all_proxies.extend(proxies)

        if all_proxies:
            fname = f"working_all_{today}.txt"
            with open(fname, "w", encoding="utf-8") as fh:
                fh.write("\n".join(sorted(set(all_proxies))) + "\n")
            written.append(fname)
    else:
        for proto, proxies in working.items():
            if not proxies:
                continue
            fname = f"working_{proto}_{today}.txt"
            with open(fname, "w", encoding="utf-8") as fh:
                fh.write("\n".join(sorted(set(proxies))) + "\n")
            written.append(fname)
    return written


def banner() -> Panel:
    total = sum(len(v) for v in SOURCES.values())
    os_name = platform.system()
    opt = "Linux (fork + fd limits)" if os_name == "Linux" else ("Windows (spawn + threads)" if os_name == "Windows" else os_name)

    sub = Text()
    sub.append("• ", style=f"bold {green}")
    sub.append(f"{total} APIs", style="bold white")
    sub.append("   •   ", style=muted)
    sub.append("HTTP / SOCKS4 / SOCKS5", style="white")
    sub.append("   •   ", style=muted)
    sub.append(opt, style=f"bold {cyan}")

    return Panel(
        sub,
        border_style=green,
        title=f"[bold {green}]ZYRE PROXY SCRAPER[/] [{muted}]& CHECKER[/]",
        subtitle=f"[{muted}]v2.0[/]",
        padding=(1, 3),
        box=box.ROUNDED,
    )


def pick_types() -> list[str]:
    total = sum(len(v) for v in SOURCES.values())
    table = Table(
        box=box.ROUNDED,
        border_style=muted,
        header_style=f"bold {green}",
        title="[bold white]Select Proxy Types[/]",
        title_justify="left",
        expand=False,
        padding=(0, 2),
    )
    table.add_column("#", justify="center", style=f"bold {cyan}")
    table.add_column("Type", style="bold white")
    table.add_column("Protocols", style=muted)
    table.add_column("APIs", justify="right", style="bold white")

    options = [
        ("1", "All", "HTTP + SOCKS4 + SOCKS5", "all"),
        ("2", "HTTP", "HTTP / HTTPS", "http"),
        ("3", "SOCKS4", "SOCKS4", "socks4"),
        ("4", "SOCKS5", "SOCKS5", "socks5"),
    ]
    counts = {
        "all": total,
        "http": len(SOURCES.get("http", [])),
        "socks4": len(SOURCES.get("socks4", [])),
        "socks5": len(SOURCES.get("socks5", [])),
    }
    for num, name, desc, key in options:
        table.add_row(num, name, desc, f"{counts[key]:,}")

    console.print(table)

    choice = Prompt.ask(
        f"[bold {green}]>[/] [bold]Choice[/bold]",
        choices=["1", "2", "3", "4"],
        default="1",
    )
    mapping = {
        "1": ["http", "socks4", "socks5"],
        "2": ["http"],
        "3": ["socks4"],
        "4": ["socks5"],
    }
    return mapping[choice]


def pick_quality(total_items: int) -> tuple[int, float, float, int]:
    peak_threads = min(800, max(100, total_items // 50))
    table = Table(
        box=box.ROUNDED,
        border_style=muted,
        header_style=f"bold {green}",
        title="[bold white]Select Quality Preset[/]",
        title_justify="left",
        expand=False,
        padding=(0, 2),
    )
    table.add_column("#", justify="center", style=f"bold {cyan}")
    table.add_column("Preset", style="bold white")
    table.add_column("Timeout", style=muted)
    table.add_column("Max Latency", style=muted)
    table.add_column("Retries", style=muted)
    table.add_column("Description", style="white")

    table.add_row("1", "ULTIMATE", "3.0s", "1500ms", "1", "Fast check, lowest ping only")
    table.add_row("2", "BALANCED", "6.0s", "3500ms", "2", "Balance of speed and working proxies")
    table.add_row("3", "RECOMMENDED", "8.0s", "6000ms", "3", "Default, max working proxies")
    table.add_row("4", "CATCH-ALL", "15.0s", "12000ms", "3", "Keeps slower proxies")
    table.add_row("5", "CUSTOM", "-", "-", "-", "Manual settings")

    console.print()
    console.print(table)

    choice = Prompt.ask(
        f"[bold {green}]>[/] [bold]Choice[/bold]",
        choices=["1", "2", "3", "4", "5"],
        default="3",
    )

    if choice == "1":
        return peak_threads, 3.0, 1500.0, 1
    if choice == "2":
        return peak_threads, 6.0, 3500.0, 2
    if choice == "3":
        return peak_threads, 8.0, 6000.0, 3
    if choice == "4":
        return peak_threads, 15.0, 12000.0, 3

    threads = IntPrompt.ask(f"[bold {green}]>[/] [bold]Threads[/bold]", default=peak_threads)
    timeout = FloatPrompt.ask(f"[bold {green}]>[/] [bold]Timeout (seconds)[/bold]", default=6.0)
    max_speed = FloatPrompt.ask(f"[bold {green}]>[/] [bold]Max latency (ms)[/bold]", default=5000.0)
    retries = IntPrompt.ask(f"[bold {green}]>[/] [bold]Connection attempts[/bold]", default=3)
    return max(1, threads), timeout, max_speed, max(1, retries)


def menu() -> str:
    table = Table(
        box=box.ROUNDED,
        border_style=muted,
        header_style=f"bold {green}",
        title="[bold white]Main Menu[/]",
        title_justify="left",
        expand=False,
        padding=(0, 2),
    )
    table.add_column("#", justify="center", style=f"bold {cyan}")
    table.add_column("Action", style="bold white")
    table.add_row("1", "Scrape and validate proxies")
    table.add_row("2", "Validate proxies from file")
    console.print(table)

    return Prompt.ask(
        f"[bold {green}]>[/] [bold]Choice[/bold]",
        choices=["1", "2"],
        default="1",
    )


def main() -> None:
    console.print()
    console.print(banner())
    console.print()

    action = menu()

    if action == "1":
        types = pick_types()

        if not socks_supported and any(t in ("socks4", "socks5") for t in types):
            console.print(
                Panel(
                    "[yellow]PySocks is not installed; SOCKS4/SOCKS5 cannot be validated.[/yellow]\n"
                    "Install with: [bold]pip install PySocks[/bold]\n"
                    "Continuing with HTTP only.",
                    title="[bold red]SOCKS Missing[/bold red]",
                    border_style="red",
                )
            )
            types = [t for t in types if t not in ("socks4", "socks5")]
            if not types:
                console.print("[red]No selectable proxy types remain. Exiting.[/red]")
                return

        console.rule(f"[bold {green}]Scraping[/]", style=muted)
        scraped = scrape(types)

        summary = Table(
            box=box.ROUNDED,
            border_style=muted,
            header_style=f"bold {green}",
            title="[bold white]Scrape Results[/]",
            title_justify="left",
            expand=False,
            padding=(0, 2),
        )
        summary.add_column("Type", style="bold white")
        summary.add_column("Unique Proxies", justify="right", style=cyan)

        grand_total = 0
        for proto in types:
            count = len(scraped.get(proto, set()))
            grand_total += count
            summary.add_row(proto.upper(), f"{count:,}")

        summary.add_section()
        summary.add_row("[bold]TOTAL[/bold]", f"[bold {green}]{grand_total:,}[/]")
        console.print(summary)

        if not grand_total:
            console.print("[red]No proxies scraped. Exiting.[/red]")
            return

        do_check = Prompt.ask(
            f"[bold {green}]>[/] [bold]Validate scraped proxies now?[/bold]",
            choices=["y", "n"],
            default="y",
        )

        if do_check.lower() == "n":
            console.rule(f"[bold {green}]Saving Raw Proxies[/]", style=muted)
            combined_choice = Prompt.ask(
                f"[bold {green}]>[/] [bold]Save all protocols into a single file?[/bold]",
                choices=["y", "n"],
                default="n",
            )
            raw = defaultdict(list)
            for proto, items in scraped.items():
                for p in items:
                    auth = f"{p[2]}:{p[3]}@" if p[2] and p[3] else ""
                    raw[proto].append(f"{auth}{p[0]}:{p[1]}")

            saved = save(raw, combined=(combined_choice.lower() == "y"))
            console.print()
            if saved:
                msg = Text()
                msg.append("  Saved: ", style=f"bold {green}")
                msg.append(", ".join(saved), style="white")
                console.print(msg)
            return

    else:
        filepath = Prompt.ask(f"[bold {green}]>[/] [bold]Path to proxy file[/bold]")
        if not os.path.exists(filepath):
            console.print("[red]File not found.[/red]")
            return

        input_types = Prompt.ask(
            f"[bold {green}]>[/] [bold]Proxy type(s) to check (e.g. http, socks5)[/bold]",
            default="http",
        )
        types = [t.strip().lower() for t in input_types.split(",") if t.strip()]
        if not types:
            types = ["http"]

        text = Path(filepath).read_text(encoding="utf-8", errors="ignore")
        parsed = parse_proxies(text)

        if not parsed:
            console.print("[red]No valid proxies found in file.[/red]")
            return

        grand_total = len(parsed) * len(types)
        console.print(
            f"Found [bold {cyan}]{len(parsed):,}[/] unique proxies. "
            f"Testing against {len(types)} protocols ([bold {cyan}]{grand_total:,}[/] total checks)."
        )
        scraped = {proto: parsed for proto in types}

    threads, timeout, max_speed, retries = pick_quality(grand_total)

    combined_ans = Prompt.ask(
        f"[bold {green}]>[/] [bold]Save all protocols into a single combined file (real-time)?[/bold]",
        choices=["y", "n"],
        default="n",
    )
    combined = combined_ans.lower() == "y"

    console.rule(f"[bold {green}]Validating[/]", style=muted)
    working = validate(
        scraped,
        threads,
        combined,
        timeout=timeout,
        max_speed=max_speed,
        retries=retries,
    )

    total_working = sum(len(v) for v in working.values())
    if total_working > 0:
        console.print()
        console.rule(f"[bold {green}]Target Ban Filter[/]", style=muted)
        console.print()
        console.print(
            f"  Found [bold {green}]{total_working:,}[/] working proxies.\n"
            f"  Test against popular services to remove proxies blocked by Cloudflare, Discord, Steam, etc."
        )

        filter_enabled, target_sites = pick_targets()
        if filter_enabled and target_sites:
            working = filter_targets(working, target_sites, timeout=timeout)
            save(working, combined=combined)

    today = date.today().isoformat()
    files = []
    if combined:
        if any(working.values()):
            files.append(f"working_all_{today}.txt")
    else:
        for proto, addrs in working.items():
            if addrs:
                files.append(f"working_{proto}_{today}.txt")

    result = Table(
        box=box.ROUNDED,
        border_style=muted,
        header_style=f"bold {green}",
        title="[bold white]Working Proxies Summary[/]",
        title_justify="left",
        expand=False,
        padding=(0, 2),
    )
    result.add_column("Type", style="bold white")
    result.add_column("Working", justify="right", style=green)
    result.add_column("File", style=muted)

    total_final = 0
    for proto in types:
        count = len(working.get(proto, []))
        total_final += count
        fname = f"working_{proto}_{today}.txt" if count else "-"
        result.add_row(proto.upper(), f"{count:,}", fname)

    result.add_section()
    result.add_row("[bold]TOTAL[/bold]", f"[bold {green}]{total_final:,}[/]", "")
    console.print(result)

    console.print()
    if files:
        done = Text()
        done.append("  Saved: ", style=f"bold {green}")
        done.append(", ".join(files), style="white")
        console.print(done)
    else:
        console.print("[yellow]No working proxies found.[/yellow]")


if __name__ == "__main__":
    mp.freeze_support()
    try:
        if "fork" in mp.get_all_start_methods():
            mp.set_start_method("fork")
        else:
            mp.set_start_method("spawn")
    except RuntimeError:
        pass

    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[red]Interrupted by user.[/red]")
