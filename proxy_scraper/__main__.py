"""Module entry point: ``python -m proxy_scraper``."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
