# Zyre Proxy Scraper &amp; Checker

Free public proxies change every day. Most lists give you a million IPs that
don't work, in formats nobody's tools can read directly. Zyre fixes both:
scrapes 150+ sources, checks each one against multiple judges, and writes
the working set out in formats ready for whatever you run next.

![preview](preview.gif)

---

## What it does

1. **Pulls** proxies from 150 live APIs and GitHub lists (HTTP, HTTPS,
   SOCKS4, SOCKS5 — with auth where supported).
2. **Checks** each one through a 2-sample latency test against 5 judge
   servers, throwing out anything too slow or too flaky.
3. **(Optional)** tags each working proxy with its country and whether it's
   transparent / anonymous / elite.
4. **Writes** everything to the format you pick — plain text, URL-form
   proxy strings, JSON with metadata, or CSV.

No proxies found in the wild are stored or shared. The tool just queries
public endpoints and writes files locally.

---

## Installation

Pick your platform:

### Windows

```
git clone https://github.com/zyrexdz/proxy-scraper-checker.git
cd proxy-scraper-checker
setup.bat
```

Or if you have Python installed:

```
pip install -r requirements.txt
python main.py
```

Or download the pre-built `ZyreProxyScraper.exe` from
[Releases](https://github.com/zyrexdz/proxy-scraper-checker/releases) — no
Python needed.

### Linux / macOS / WSL

```bash
git clone https://github.com/zyrexdz/proxy-scraper-checker.git
cd proxy-scraper-checker
chmod +x setup.sh && ./setup.sh
```

Or manually:

```bash
pip install -r requirements.txt
python3 main.py
```

Ubuntu users who hit a `externally-managed-environment` error from pip:

```bash
pip install --break-system-packages -r requirements.txt
# or
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
```

Requires **Python 3.9 or newer**. Tested on Windows 11, Ubuntu 22.04,
macOS 13.

---

## Using it

### The wizard

Run `python main.py` with no flags and you'll get a 4-step wizard:

```
What next?
  1  Scrape + validate       ← pulls fresh + checks (default)
  2  Scrape only              ← pulls fresh, no checking, raw output
  3  Validate a file          ← re-checks a list you already have
  4  Quit

Protocols          HTTP, SOCKS4, SOCKS5 (toggle with 1,2,3)
Output formats     txt / txt-url / json / csv / combined
Quality preset     ULTIMATE, BALANCED, RECOMMENDED, CATCH-ALL
Target filter      Drop proxies banned on Cloudflare, Discord, etc.
```

Answer each one (or just press Enter for the default), then say `y` to run.

### Common commands

```bash
# One-shot, no prompts, sensible defaults.
python main.py --non-interactive

# JSON output, for piping into another tool.
python main.py --non-interactive --preset balanced -f json

# Just HTTP, snappiest proxies only.
python main.py --protocol http --preset ultimate -f txt-url

# Re-validate a list you already have.
python main.py proxies.txt --non-interactive

# Include the experimental HTML scrapers (slower, more hits).
python main.py --extra-sources
```

### Use it as a Python library

```python
import asyncio
from proxy_scraper import scraper, checker
from proxy_scraper.protocols import Protocol
from proxy_scraper.sources import sources_by_protocol

async def main():
    sources = [s for ss in sources_by_protocol([Protocol.HTTP]).values() for s in ss]
    scraped = await scraper.scrape(sources)
    results = await checker.check_all(scraped, concurrency=200)
    print(f"{sum(1 for r in results if r.ok)} working")

asyncio.run(main())
```

---

## Output formats

Pick one or more with `-f`:

| Format     | One line per proxy looks like                                  |
|------------|--------------------------------------------------------------|
| `txt`      | `1.2.3.4:8080`                                                |
| `txt-url`  | `socks5h://user:pass@5.6.7.8:1080` ← drop-in for `curl --proxy` |
| `json`     | `{ "ip": "...", "port": ..., "latency_ms": 120, "country": "US" }` |
| `csv`      | `ip,port,protocol,user,passwd,latency_ms,country,anonymity` |

`txt` and `txt-url` write one file per protocol. `json`, `csv`, and
`combined` write single files with everything.

---

## Quality presets

| Preset        | Timeout | Max ping | Tries | What it does                                 |
|---------------|---------|----------|-------|----------------------------------------------|
| **BALANCED**  | 6.0s    | 3.5s     | 2     | Best yield for the time. *(default)*         |
| **ULTIMATE**  | 3.0s    | 1.5s     | 1     | Only the snappiest proxies — slow on big lists |
| **RECOMMENDED** | 8.0s  | 6.0s     | 3     | Most working proxies, slowest                |
| **CATCH-ALL** | 15.0s   | 12.0s    | 3     | Includes slow / distant proxies               |

For very large scrapes (500k+ candidates), start with **BALANCED**. If
you only need a handful of elite proxies, switch to **ULTIMATE** and be
patient.

Override any value on the command line:

```bash
python main.py --preset balanced --concurrency 500 --timeout 4 --retries 3
```

---

## Live dashboard

When your terminal supports it, the checker runs under a multi-panel
live display:

```
+----------------------------------------------------------------+
|  ZYRE  VALIDATING    http,socks5    11,385 cpm                  |
+----------------------------------------------------------------+
| [=========================         ]  80.0%        |  Working    12
|  80 of 100 checked                  |  Hit avg    15.0%
| working: 12  hit: 15.0%  recent: 23% |  Hit recent 23.3%
|                                     |  CPM        11,385
| sources: 150  threads: 200          |  Progress   80.0%
+-------------------------------------+-----------+
+----- Events -----------------------------------------------+
|  + 15:24:46  discord.com -> 200                             |
|  x 15:24:46  spys.one timeout                               |
+------------------------------------------------------------+
```

In CMD without ANSI (or when output is piped to a file), it falls back to
plain one-line-per-update progress — no broken escape codes.

---

## Where the proxies come from

74 HTTP + 35 SOCKS4 + 41 SOCKS5 = 150 standard sources (158 if you opt in
to the experimental HTML scrapers via `--extra-sources`).

Mix of:
- **APIs** — Proxyscrape v2/v4, OpenProxy, Geonode, Proxifly, PubProxy,
  Imtaqin, Proxyscan
- **GitHub lists** — TheSpeedX, monosans, ShiftyTR, Clarketm, roosterkid,
  vakhov, zevtyardt, prxchk, ALIILAPRO, hookzof, jetkai, proxy4parsing,
  proxifly, VPSLabCloud, adasd223, dpangestuw, r00tee, gfpcom, mmpx12,
  iplocate, hproxy-com, SoliSpirit, databay-labs, ProxyScrape,
  proxygenerator1, vmheaven, xyzs996, elliottophellia, ClearProxy,
  openproxyhub, rix4uni, Thordata, saisuiu

Each source's success / failure history is persisted to
`sources_health.json`. Sources that fail 5 times in a row are auto-skipped
on the next run, so dead endpoints stop slowing you down without you
having to maintain the list.

---

## Configuration (optional)

Drop a `config.toml` next to `main.py` to set defaults:

```toml
[scraper]
timeout = 20.0
concurrency = 200

[checker]
timeout = 8.0
retries = 3
concurrency = 400
max_latency_ms = 5000.0

[output]
formats = ["txt", "json"]
out_dir = "./output"

[filter]
enabled = true
targets = ["Cloudflare", "Discord"]
```

Or via environment variables (`ZPS_` prefix):

```bash
ZPS_CHECKER_TIMEOUT=5.0
ZPS_OUTPUT_FORMATS="txt,json"
```

---

## Privacy

Zyre doesn't run its own proxy network and doesn't store anything from any
source. It only:

- pulls from public APIs and GitHub raw files,
- sends a few HTTP requests per candidate through a rotating judge set
  (api.ipify.org, checkip.amazonaws.com, ifconfig.me, ifconfig.io,
  httpbin.org), and
- optionally queries ip-api.com (45 req/min free tier) for the ISO country
  code of working proxies.

Nothing leaves your machine except those queries, and nothing about you
gets stored.

---

## Development

```bash
pip install -e ".[dev]"
pytest             # 61 tests, no network required
ruff check .
mypy proxy_scraper
```

Adding a source is a one-line edit to `proxy_scraper/sources.py`:

```python
Source("https://raw.githubusercontent.com/<user>/<repo>/main/list.txt", Protocol.HTTP)
```

---

## License

MIT — see [LICENSE](LICENSE).
