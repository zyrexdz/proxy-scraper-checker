"""Configuration loading.

Settings are resolved in this order (lowest priority first):

    1. Built-in defaults.
    2. ``config.toml`` in the current working directory, if present.
    3. Environment variables prefixed with ``ZPS_``.

Example config.toml::

    [scraper]
    timeout = 20.0
    concurrency = 80

    [checker]
    timeout = 8.0
    retries = 2
    concurrency = 250

    [output]
    formats = ["txt", "json"]
    out_dir = "./output"
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# We're avoiding a `tomllib`/`tomli` dependency to keep the requirement set
# small. Our TOML needs are trivial (flat key=value pairs), and a minimal
# parser is fine for the value surface.
import re

_KV_RE = re.compile(r'^\s*([A-Za-z_][\w.-]*)\s*=\s*(.+?)\s*$')
_TABLE_RE = re.compile(r"^\s*\[([A-Za-z_][\w.-]*)\]\s*$")
_LIST_RE = re.compile(r"^\s*\[(.+)\]\s*$")


def _parse_value(raw: str) -> Any:
    raw = raw.strip()
    if raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1]
    if raw.startswith("'") and raw.endswith("'"):
        return raw[1:-1]
    if raw in ("true", "True"):
        return True
    if raw in ("false", "False"):
        return False
    if raw in ("null", "None"):
        return None
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw  # leave as string


def _parse_toml_minimal(text: str) -> dict[str, Any]:
    """Parse a tiny subset of TOML: tables, scalar values, list literals.

    This deliberately does not support nested tables, dotted keys, multi-line
    strings, or escape sequences — none of those are needed for our config.
    """
    root: dict[str, Any] = {}
    table: dict[str, Any] = root
    table_name: str | None = None
    for line in text.splitlines():
        line = line.split("#", 1)[0].rstrip()
        if not line:
            continue
        if (m := _TABLE_RE.match(line)):
            table_name = m.group(1)
            root[table_name] = root.get(table_name, {})
            table = root[table_name]
            continue
        if (m := _KV_RE.match(line)):
            key, raw = m.group(1), m.group(2)
            # Inline list literal
            if raw.startswith("[") and raw.endswith("]"):
                inner = raw[1:-1]
                items = [_parse_value(x.strip()) for x in _split_top_level(inner, ",")]
                table[key] = items
            else:
                table[key] = _parse_value(raw)
    return root


def _split_top_level(text: str, sep: str) -> list[str]:
    """Split on ``sep`` while respecting bracket nesting and quoting."""
    parts: list[str] = []
    buf = []
    depth = 0
    in_str = None
    for ch in text:
        if in_str:
            buf.append(ch)
            if ch == in_str:
                in_str = None
            continue
        if ch in "'\"":
            in_str = ch
            buf.append(ch)
            continue
        if ch in "[(":
            depth += 1
        elif ch in "])":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return parts


@dataclass
class ScraperConfig:
    timeout: float = 15.0
    concurrency: int = 150


@dataclass
class CheckerConfig:
    timeout: float = 8.0
    retries: int = 2
    concurrency: int = 300
    max_latency_ms: float = 5000.0
    two_sample: bool = True


@dataclass
class OutputConfig:
    formats: list[str] = field(default_factory=lambda: ["txt"])
    out_dir: str = "."
    combined: bool = False


@dataclass
class FilterConfig:
    enabled: bool = False
    targets: list[str] = field(default_factory=list)
    timeout: float = 8.0


@dataclass
class EnrichmentConfig:
    anonymity: bool = False
    geo: bool = False


@dataclass
class Config:
    scraper: ScraperConfig = field(default_factory=ScraperConfig)
    checker: CheckerConfig = field(default_factory=CheckerConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    filter: FilterConfig = field(default_factory=FilterConfig)
    enrichment: EnrichmentConfig = field(default_factory=EnrichmentConfig)
    types: list[str] = field(default_factory=lambda: ["http", "socks4", "socks5"])

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        """Load from a TOML file (if provided and exists), then overlay env vars."""
        data: dict[str, Any] = {}
        path = Path(path) if path else Path("config.toml")
        if path.exists():
            try:
                data = _parse_toml_minimal(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                data = {}

        cfg = cls()
        for section in ("scraper", "checker", "output", "filter", "enrichment"):
            sub = data.get(section, {})
            obj = getattr(cfg, section)
            for k, v in sub.items():
                if hasattr(obj, k):
                    setattr(obj, k, v)
        if "types" in data:
            cfg.types = list(data["types"])

        # Env-var overrides — ZPS_<SECTION>_<KEY>.
        for section in ("scraper", "checker", "output", "filter", "enrichment"):
            obj = getattr(cfg, section)
            prefix = f"ZPS_{section.upper()}_"
            for k in vars(obj):
                env = f"{prefix}{k.upper()}"
                if env in os.environ:
                    raw = os.environ[env]
                    target_type = type(getattr(obj, k))
                    try:
                        if target_type is bool:
                            setattr(obj, k, raw.lower() in ("1", "true", "yes", "y"))
                        elif target_type is list:
                            setattr(obj, k, [x.strip() for x in raw.split(",") if x.strip()])
                        else:
                            setattr(obj, k, target_type(raw))
                    except (TypeError, ValueError):
                        pass
        return cfg
