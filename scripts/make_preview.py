"""Generate a v3 demo GIF that shows the new wizard + dashboard UI.

The real tool would be recorded in Windows Terminal / similar; this script
renders a series of frames programmatically so the README has a
non-stale preview. Replace by re-running this script after any major
UI change.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


# Monospace font that ships with Pillow's default on Windows.
def _font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in (
        "consola.ttf",       # Windows
        "Consolas",
        "Menlo.ttc",         # macOS
        "DejaVuSansMono.ttf",  # Linux
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    ):
        try:
            return ImageFont.truetype(candidate, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


_FONT_BIG = _font(22)
_FONT = _font(16)
_FONT_SMALL = _font(13)

W, H = 900, 540
BG = (15, 17, 21)
FG = (220, 230, 240)
GREEN = (0, 229, 168)
CYAN = (56, 189, 248)
MUTED = (140, 150, 165)
RED = (244, 63, 94)
YELLOW = (251, 191, 36)
GREY_PANEL = (24, 28, 34)
GREY_LINE = (50, 56, 64)
BORDER = (60, 70, 80)


def _frame() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W, H), BG)
    return img, ImageDraw.Draw(img)


def _text(draw, xy, text, *, fill=FG, font=None):
    draw.text(xy, text, fill=fill, font=font or _FONT)


def _panel(draw, box, *, border=GREEN):
    x0, y0, x1, y1 = box
    draw.rectangle([x0, y0, x1, y1], fill=GREY_PANEL, outline=border, width=1)


def _bar(draw, x, y, w, h, fill_pct, *, fill=GREEN, track=GREY_LINE):
    draw.rectangle([x, y, x + w, y + h], fill=track)
    fw = max(0, int(w * fill_pct / 100))
    if fw:
        draw.rectangle([x, y, x + fw, y + h], fill=fill)


def render_frame_banner() -> Image.Image:
    img, draw = _frame()
    # Banner box
    _panel(draw, (40, 30, W - 40, 90), border=BORDER)
    _text(draw, (60, 45), "ZYRE  PROXY SCRAPER", font=_FONT_BIG, fill=GREEN)
    _text(draw, (60, 75), "v3.0.0", fill=MUTED)
    return img


def render_frame_wizard_action() -> Image.Image:
    img, draw = _frame()
    img.paste(render_frame_banner(), (0, 0))
    # Wizard
    y = 120
    _text(draw, (60, y), "What next?", fill=GREEN, font=_FONT_BIG)
    y += 50
    rows = [
        ("1", "Scrape + validate", "← default"),
        ("2", "Scrape only (raw, no check)", ""),
        ("3", "Validate a file", ""),
        ("4", "Quit", ""),
    ]
    for num, action, note in rows:
        _text(draw, (90, y), num, fill=CYAN, font=_FONT_BIG)
        _text(draw, (130, y), action, font=_FONT_BIG)
        if note:
            _text(draw, (430, y + 4), note, fill=MUTED)
        y += 40
    return img


def render_frame_wizard_protocols() -> Image.Image:
    img, draw = _frame()
    img.paste(render_frame_wanner_top(), (0, 0))
    y = 220
    _text(draw, (60, y), "Protocols", fill=GREEN, font=_FONT_BIG)
    y += 50
    for i, (num, name) in enumerate([("1", "HTTP"), ("2", "SOCKS4"), ("3", "SOCKS5")]):
        _text(draw, (90, y), num, fill=CYAN, font=_FONT_BIG)
        _text(draw, (130, y), name, font=_FONT_BIG)
        y += 40
    return img


def render_frame_wanner_top() -> Image.Image:
    """Top portion (banner + first wizard) — reused as background."""
    img, draw = _frame()
    return img  # transparent compositing only via paste


def render_frame_dashboard(pct: int, working: int, hit: float, recent: float, cpm: int,
                          events: list[tuple[str, str]]) -> Image.Image:
    img, draw = _frame()
    # Header
    _panel(draw, (20, 14, W - 20, 60), border=BORDER)
    _text(draw, (35, 25), "ZYRE", font=_FONT_BIG, fill=GREEN)
    _text(draw, (115, 30), "VALIDATING", fill=CYAN, font=_FONT)
    _text(draw, (235, 30), "http,socks5", fill=FG, font=_FONT)
    _text(draw, (W - 200, 30), f"{cpm:,} cpm", fill=YELLOW, font=_FONT)
    # Body split
    body_top = 76
    body_bot = H - 110
    # Left (progress)
    _panel(draw, (20, body_top, W - 270, body_bot), border=BORDER)
    _bar(draw, 45, body_top + 20, W - 320, 10, pct, fill=GREEN)
    _text(draw, (45, body_top + 40), f"{pct:5.1f}%", fill=FG, font=_FONT_BIG)
    y = body_top + 90
    _text(draw, (45, y), f"{int(pct * 1000):,} of 1,000 checked", fill=FG, font=_FONT)
    y += 30
    _text(draw, (45, y), f"working: {working:,}", fill=GREEN, font=_FONT_BIG)
    _text(draw, (200, y + 8), f"hit: {hit:.1f}%", fill=CYAN, font=_FONT)
    _text(draw, (320, y + 8), f"recent: {recent:.1f}%", fill=CYAN, font=_FONT)
    y += 40
    _text(draw, (45, y), "sources: 150   threads: 400", fill=MUTED, font=_FONT_SMALL)
    # Right (stats)
    _panel(draw, (W - 250, body_top, W - 20, body_bot), border=GREEN)
    y = body_top + 14
    _text(draw, (W - 235, y), "Live stats", fill=GREEN, font=_FONT)
    y += 30
    for label, value, color in [
        ("Working",      f"{working:,}",        FG),
        ("Hit (avg)",    f"{hit:.1f}%",          CYAN),
        ("Hit (recent)", f"{recent:.1f}%",       CYAN),
        ("CPM",          f"{cpm:,}",             YELLOW),
        ("Progress",     f"{pct:.1f}%",          FG),
    ]:
        _text(draw, (W - 235, y), label, fill=MUTED, font=_FONT_SMALL)
        _text(draw, (W - 70, y), value, fill=color, font=_FONT)
        y += 30
    # Footer (events)
    foot_top = H - 96
    _panel(draw, (20, foot_top, W - 20, H - 20), border=BORDER)
    _text(draw, (35, foot_top + 8), "Events", fill=GREEN, font=_FONT)
    y = foot_top + 36
    for kind, msg in events[-6:]:
        sym_color = (GREEN if kind == "ok" else (RED if kind == "fail" else CYAN))
        sym = "+" if kind == "ok" else ("x" if kind == "fail" else "*")
        _text(draw, (45, y), sym, fill=sym_color, font=_FONT)
        _text(draw, (65, y), msg, fill=FG, font=_FONT_SMALL)
        y += 18
    return img


def main() -> Path:
    frames = []
    # Frame 1: banner
    frames.append(render_frame_banner())
    # Frame 2: wizard action
    frames.append(render_frame_wizard_action())
    # Frame 3: protocols step
    frames.append(render_frame_wizard_protocols())
    # Dashboard frames showing progress
    progress_points = [
        (5,   12,  4.0, 12.0,  800, [("ok", "proxifly.com   -> 200"), ("ok", "speedx list   -> 200"), ("fail", "vakhov list    -> 502")]),
        (28, 180,  8.4, 14.2, 3200, [("ok", "discord.com    -> 200"), ("ok", "cloudflare.com -> 200"), ("fail", "spys.one       -> timeout")]),
        (62, 510,  9.6, 12.1, 6800, [("ok", "youtube.com    -> 200"), ("ok", "monosans list  -> 200"), ("fail", "free-proxy.net -> 403")]),
        (88, 760,  8.9,  9.5, 9200, [("ok", "github raw     -> 200"), ("ok", "openproxy.io   -> 200"), ("ok", "databay-labs   -> 200")]),
    ]
    for pct, working, hit, recent, cpm, events in progress_points:
        frames.append(render_frame_dashboard(pct, working, hit, recent, cpm, events))

    # Hold the last frame longer for readability
    out = Path("preview.gif")
    durations = [1500, 1800, 1500, 800, 800, 800, 1500]
    if len(durations) != len(frames):
        durations = [1200] * len(frames)
    frames[0].save(
        out,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
    )
    return out


if __name__ == "__main__":
    p = main()
    print(f"wrote {p} ({p.stat().st_size // 1024} KB)")
