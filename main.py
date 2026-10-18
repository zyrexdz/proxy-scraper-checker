#!/usr/bin/env python3
"""Top-level launcher for backwards-compat with the v2.0 entry point name."""

from proxy_scraper.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
