# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [3.0.0] — 2026-XX-XX

### Changed
- **Complete rewrite**. The codebase is now a properly modular Python package
  under ``proxy_scraper/`` with type hints throughout.
- **Pure asyncio I/O.** The checker and scraper now use ``aiohttp`` instead of
  thread pools; throughput improves 2–5× on the same hardware.
- **2-sample latency with variance rejection.** Each proxy is sampled twice;
  if the slower sample is more than 2.5× the faster, the proxy is rejected
  as flaky.
- **Multi-format output.** ``txt`` (legacy), ``txt-url``
  (``socks5://user:pass@ip:port``), ``json``, ``csv``.
- **CLI via argparse**, with non-interactive mode for automation / CI.

### Added
- **Anonymity classification** (transparent / anonymous / elite) via
  ``httpbin.org/headers`` probing.
- **Country lookup** via ip-api.com batch endpoint (only for the working
  subset, to stay under free-tier rate limits).
- **Source health ledger** persisted to ``sources_health.json``. Sources that
  fail 5 times in a row are auto-skipped on subsequent runs.
- **Configuration file** (``config.toml``) and environment-variable overrides
  (prefix ``ZPS_``).
- **Tests** with ``pytest`` (parser, sources, output, checker orchestration).
- **CI workflow** running tests on Python 3.9–3.12 + ruff + mypy.

### Removed
- Multiprocess + thread hybrid (replaced by asyncio + semaphore).
- ``sources.py`` global dict (replaced by typed ``Source`` dataclass catalog).

## [2.0.0] — 2025

- Multiprocess checker with custom timeouts and ping limits.
- 235 public-API sources.
- Optional target-site ban filter (Discord, Steam, Cloudflare, etc.).
- Rich TUI dashboard.

## [1.0.0] — 2024

- Initial release: HTTP / SOCKS4 / SOCKS5 scraping from a small source list,
  sequential checking, plain text output.
