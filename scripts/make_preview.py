"""Generate the v3 demo GIF.

Renders a multi-stage demo of the tool's UX: banner → wizard summary →
live dashboard animating from 0% to 100% with event log streaming,
numbered metrics ticking up in real-time. Output: ``preview.gif``.

Run from the repo root::

    python scripts/make_preview.py

Replace by re-running whenever the UX changes.
"""

from __future__ import annotations

import random
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# Theme — pulled straight from proxy_scraper/ui.py so the GIF matches the
# actual Rich Console output.
# ---------------------------------------------------------------------------

W, H = 980, 580
BG = (15, 17, 21)                 # rich default
PANEL = (24, 28, 34)
PANEL_BORDER = (60, 70, 80)
HEADER_BORDER = (0, 229, 168)     # GREEN
SUBTLE = (50, 56, 64)
GREEN = (0, 229, 168)
CYAN = (56, 189, 248)
MUTED = (140, 150, 165)
RED = (244, 63, 94)
YELLOW = (251, 191, 36)
FG = (220, 230, 240)


def _font(size: int) -> ImageFont.ImageFont:
    for cand in (
        "consola.ttf", "Consolas",
        "C:/Windows/Fonts/consola.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
        "/System/Library/Fonts/Menlo.ttc",
    ):
        try:
            return ImageFont.truetype(cand, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


F_BIG = _font(28)
F = _font(17)
F_SM = _font(13)
F_TINY = _font(11)


def _img() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W, H), BG)
    return img, ImageDraw.Draw(img)


def _rounded_rect(draw, box, *, radius=6, fill=None, outline=None, width=1):
    x0, y0, x1, y1 = box
    if fill is not None:
        draw.rounded_rectangle(box, radius=radius, fill=fill)
    if outline is not None:
        draw.rounded_rectangle(box, radius=radius, outline=outline, width=width)


def _panel(draw, box, *, border=PANEL_BORDER, fill=PANEL, radius=6):
    _rounded_rect(draw, box, radius=radius, fill=fill, outline=border)


def _bar(draw, x, y, w, h, fill_pct, *, fill=GREEN, track=SUBTLE):
    _rounded_rect(draw, (x, y, x + w, y + h), radius=3, fill=track)
    fw = max(0, int(w * fill_pct / 100))
    if fw > 4:
        _rounded_rect(draw, (x, y, x + fw, y + h), radius=3, fill=fill)


def _txt(draw, xy, text, *, fill=FG, font=None):
    draw.text(xy, text, fill=fill, font=font or F)


def _wrap_text(draw, text, x, y, max_w, font):
    """Right-truncate to fit a max width and return the truncated string."""
    bbox = draw.textbbox((0, 0), text, font=font)
    full_w = bbox[2] - bbox[0]
    if full_w <= max_w:
        return text
    # binary-search-ish truncation
    while len(text) > 4:
        text = text[:-2]
        bbox = draw.textbbox((0, 0), text + "...", font=font)
        if bbox[2] - bbox[0] <= max_w:
            return text + "..."
    return "..."


# ---------------------------------------------------------------------------
# Frame renderers — one per "scene".
# ---------------------------------------------------------------------------


def render_banner() -> Image.Image:
    img, draw = _img()
    # Outer banner box.
    _panel(draw, (40, 70, W - 40, 145), border=HEADER_BORDER, fill=PANEL)
    _txt(draw, (75, 90), "ZYRE  PROXY SCRAPER", font=F_BIG, fill=GREEN)
    _txt(draw, (75, 130), "v3.0.0", fill=MUTED)
    # Subtitle / stats on the right.
    _txt(draw, (W - 360, 90), "150 sources", fill=FG, font=F)
    _txt(draw, (W - 360, 115), "HTTP / SOCKS4 / SOCKS5", fill=MUTED, font=F_SM)
    _txt(draw, (W - 360, 138), "async I/O + multi-judge", fill=CYAN, font=F_SM)
    return img


def render_wizard_step(step: str, *, picked: str = "") -> Image.Image:
    """step = 'action' | 'protocols' | 'formats' | 'preset' | 'plan' """
    img, draw = _img()
    img.paste(render_banner(), (0, 0))

    # Wizard section header
    section_y = 180
    headers = {
        "action": "What next?",
        "protocols": "Protocols",
        "formats": "Output formats",
        "preset": "Quality preset",
        "plan": "Plan",
    }
    _txt(draw, (60, section_y), headers[step], font=F_BIG, fill=GREEN)
    section_y += 60

    body_x = 80
    body_y = section_y
    if step == "action":
        rows = [
            ("1", "Scrape + validate", "← default"),
            ("2", "Scrape only (raw, no check)", ""),
            ("3", "Validate a file", ""),
            ("4", "Quit", ""),
        ]
        for n, label, note in rows:
            _txt(draw, (body_x, body_y), n, fill=CYAN, font=F_BIG)
            _txt(draw, (body_x + 50, body_y + 6), label, font=F_BIG)
            if note:
                _txt(draw, (body_x + 550, body_y + 12), note, fill=MUTED, font=F_SM)
            body_y += 50
    elif step == "protocols":
        for n, name in [("1", "HTTP"), ("2", "SOCKS4"), ("3", "SOCKS5")]:
            _txt(draw, (body_x, body_y), n, fill=CYAN, font=F_BIG)
            _txt(draw, (body_x + 50, body_y + 6), name, font=F_BIG)
            body_y += 50
        # subtle highlight bar
        _bar(draw, body_x, body_y + 10, 250, 4, 100, fill=GREEN)
        _txt(draw, (body_x, body_y + 30), "toggle 1,3 — enter for all", fill=MUTED, font=F_SM)
    elif step == "formats":
        for n, name in [("1", "txt"), ("2", "txt-url"), ("3", "json"), ("4", "csv"), ("5", "combined")]:
            _txt(draw, (body_x, body_y), n, fill=CYAN, font=F_BIG)
            _txt(draw, (body_x + 50, body_y + 6), name, font=F_BIG)
            body_y += 42
    elif step == "preset":
        presets = [
            ("1", "ULTIMATE",    "3.0s",  "1500ms", "1"),
            ("2", "BALANCED",    "6.0s",  "3500ms", "2"),
            ("3", "RECOMMENDED", "8.0s",  "6000ms", "3"),
            ("4", "CATCH-ALL",   "15.0s", "12000ms", "3"),
        ]
        for n, name, t, p, r in presets:
            _txt(draw, (body_x, body_y), n, fill=CYAN, font=F_BIG)
            _txt(draw, (body_x + 50, body_y + 4), name, font=F_BIG, fill=GREEN if name == picked else FG)
            _txt(draw, (body_x + 240, body_y + 8), t, fill=FG, font=F_SM)
            _txt(draw, (body_x + 320, body_y + 8), p, fill=FG, font=F_SM)
            _txt(draw, (body_x + 420, body_y + 8), r, fill=FG, font=F_SM)
            body_y += 45
    elif step == "plan":
        rows = [
            ("Action",       "scrape + validate"),
            ("Protocols",    "http, socks4, socks5"),
            ("Output",       "txt, json"),
            ("Preset",       "balanced (timeout 6.0s, max ping 3500ms)"),
            ("Concurrency",  "300 threads"),
            ("Filter",       "off"),
            ("Output dir",   "."),
        ]
        for label, val in rows:
            _txt(draw, (body_x, body_y), label, fill=CYAN, font=F)
            _txt(draw, (body_x + 200, body_y), val, fill=FG, font=F_BIG)
            body_y += 36
        # Final confirm
        body_y += 20
        _txt(draw, (body_x, body_y), ">", fill=GREEN, font=F_BIG)
        _txt(draw, (body_x + 30, body_y), " run with this plan? [Y/n]: y", fill=FG, font=F)
    return img


def render_dashboard(
    *,
    pct: float,
    checked: int,
    total: int,
    working: int,
    hit: float,
    recent: float,
    cpm: int,
    events: list[tuple[str, str]],
    phase: str = "VALIDATING",
) -> Image.Image:
    img, draw = _img()

    # ----- Header -----
    _panel(draw, (20, 14, W - 20, 60), border=HEADER_BORDER, fill=PANEL)
    _txt(draw, (35, 25), " ZYRE ", font=F_BIG, fill=GREEN)
    _txt(draw, (140, 30), phase, fill=CYAN, font=F)
    _txt(draw, (245, 30), "http, socks5", fill=FG, font=F)
    _txt(draw, (W - 175, 30), f"{cpm:,} cpm", fill=YELLOW, font=F)

    # ----- Body split -----
    body_top = 76
    body_bot = H - 110
    body_left_x = 20
    body_right_x = W - 270

    # Left panel — progress
    _panel(draw, (body_left_x, body_top, body_right_x, body_bot), border=PANEL_BORDER, fill=PANEL)
    _bar(draw, 40, body_top + 22, body_right_x - body_left_x - 40, 12, pct, fill=GREEN)
    _txt(draw, (40, body_top + 50), f"{pct:5.1f}%", fill=FG, font=F_BIG)
    _txt(draw, (40, body_top + 90), f"{checked:,} of {total:,} checked", fill=FG, font=F)
    _txt(draw, (40, body_top + 120), f"working: ", fill=MUTED, font=F)
    _txt(draw, (40 + 95, body_top + 118), f"{working:,}", fill=GREEN, font=F_BIG)
    _txt(draw, (40, body_top + 155), "hit: ", fill=MUTED, font=F)
    _txt(draw, (40 + 50, body_top + 153), f"{hit:.1f}%", fill=CYAN, font=F_BIG)
    _txt(draw, (200, body_top + 153), "recent: ", fill=MUTED, font=F)
    _txt(draw, (200 + 80, body_top + 153), f"{recent:.1f}%", fill=CYAN, font=F_BIG)
    _txt(draw, (40, body_top + 200), "sources: 150   threads: 300", fill=MUTED, font=F_SM)
    # Add a small "currently checking" indicator that animates.
    cursor_x = 40 + int((body_right_x - body_left_x - 80) * pct / 100)
    draw.ellipse([cursor_x - 4, body_top + 25, cursor_x + 4, body_top + 33], fill=CYAN)

    # Right panel — stats
    _panel(draw, (body_right_x + 10, body_top, W - 20, body_bot), border=HEADER_BORDER, fill=PANEL)
    _txt(draw, (body_right_x + 25, body_top + 14), " Live stats", font=F, fill=GREEN)
    stats = [
        ("Working",      f"{working:,}",       FG),
        ("Hit (avg)",    f"{hit:.1f}%",         CYAN),
        ("Hit (recent)", f"{recent:.1f}%",      CYAN),
        ("CPM",          f"{cpm:,}",            YELLOW),
        ("Progress",     f"{pct:.1f}%",         FG),
    ]
    y = body_top + 50
    for label, val, color in stats:
        _txt(draw, (body_right_x + 25, y), label, fill=MUTED, font=F_SM)
        _txt(draw, (body_right_x + 195, y), val, fill=color, font=F)
        y += 36

    # ----- Footer events -----
    foot_top = H - 96
    _panel(draw, (20, foot_top, W - 20, H - 20), border=PANEL_BORDER, fill=PANEL)
    _txt(draw, (35, foot_top + 8), " Events", font=F, fill=GREEN)
    y = foot_top + 36
    # Show 6 most recent events.
    for kind, msg in (events or [])[-6:]:
        sym_color = (GREEN if kind == "ok" else (RED if kind == "fail" else CYAN))
        sym = "+" if kind == "ok" else ("x" if kind == "fail" else "*")
        _txt(draw, (45, y), sym, fill=sym_color, font=F)
        truncated = _wrap_text(draw, msg, 45, y, W - 100, F_SM)
        _txt(draw, (68, y + 2), truncated, fill=FG, font=F_SM)
        y += 18

    return img


def render_done(*, total_working: int, saved_files: list[str]) -> Image.Image:
    """Final frame: dashboard at 100% with a 'Saved' row across the bottom."""
    # Render the dashboard at 100% directly into an image, then crop the
    # events footer short and add a green 'Saved' line in its place.
    img, draw = _img()
    img.paste(render_dashboard(
        pct=100.0,
        checked=8_500,
        total=8_500,
        working=total_working,
        hit=7.2,
        recent=7.5,
        cpm=4200,
        events=[("ok", "complete"), ("ok", "discord.com -> 200"), ("ok", "github.com -> 200")],
        phase="DONE",
    ), (0, 0))
    # Overwrite the empty 'Events' footer with a 'Saved' banner.
    saved_y = H - 96
    _panel(draw, (20, saved_y, W - 20, H - 20), border=HEADER_BORDER, fill=PANEL)
    _txt(draw, (35, saved_y + 8), "[done]", fill=GREEN, font=F_BIG)
    _txt(draw, (150, saved_y + 13), f"{total_working:,} working proxies from 150 sources", fill=FG, font=F)
    _txt(draw, (35, saved_y + 50), "Saved:", fill=GREEN, font=F)
    _txt(draw, (130, saved_y + 50), ", ".join(saved_files), fill=FG, font=F_SM)
    return img


# ---------------------------------------------------------------------------
# Main: assemble a coherent ~5s demo from the frames above.
# ---------------------------------------------------------------------------


def synthesize_metrics(steps: int) -> list[dict]:
    """Smoothly interpolate working/hit/recent/cpm through the run.

    Models an S-curve where hit rate briefly spikes when easy sources
    are checked first and slows down as harder ones come in.
    """
    out = []
    for i in range(steps):
        t = i / max(1, steps - 1)              # 0..1
        pct = 100 * t
        # Smooth-ish cumulative working count
        growth = 1 - (1 - t) ** 2.4            # mild S-curve
        working = int(8_500 * growth)
        # Hit rate climbs to ~7% with mild oscillation
        hit = min(7.8, 1.5 + t * 6.0) + (random.uniform(-0.4, 0.4) if i > 3 else 0)
        recent = min(8.4, 0.5 + t * 7.5) + (random.uniform(-0.6, 0.6) if i > 4 else 0)
        cpm = int(3_000 + 1_400 * t + random.uniform(-200, 200))
        out.append(dict(
            pct=pct,
            checked=int(8_500 * t),
            total=8_500,
            working=max(working, 0),
            hit=hit,
            recent=recent,
            cpm=max(cpm, 100),
        ))
    return out


def synthesize_events(total: int, working_estimate: int) -> list[tuple[str, str]]:
    """Build a believable scrolling event log of size `total`."""
    real_targets = [
        ("discord.com", "ok"), ("cloudflare.com", "ok"),
        ("github.com", "ok"), ("google.com", "ok"),
        ("youtube.com", "ok"), ("amazon.com", "ok"),
    ]
    fail_targets = [
        ("spys.one", "fail"), ("vakhov.list", "fail"),
        ("api.spys", "timeout"), ("dead-list.io", "fail"),
    ]
    out: list[tuple[str, str]] = []
    rng = random.Random(42)
    for i in range(total):
        if i < working_estimate and rng.random() < 0.78:
            t, kind = rng.choice(real_targets)
            code = rng.choice([200, 200, 200, 304])
            out.append(("ok", f"{t:<18} -> {code}"))
        else:
            t, kind = rng.choice(fail_targets)
            code = rng.choice([503, 429, "timeout"])
            out.append(("fail", f"{t:<18} -> {code}"))
    return out


def main() -> Path:
    rng = random.Random(42)
    random.seed(42)

    frames: list[Image.Image] = []
    durations: list[int] = []

    # 1) Banner — single brief shot
    frames.append(render_banner())
    durations.append(900)

    # 2) Wizard steps — fast cuts, 4 frames total
    frames.append(render_wizard_step("action"))
    durations.append(700)
    frames.append(render_wizard_step("protocols"))
    durations.append(500)
    frames.append(render_wizard_step("formats"))
    durations.append(500)
    frames.append(render_wizard_step("preset", picked="BALANCED"))
    durations.append(800)
    frames.append(render_wizard_step("plan"))
    durations.append(800)

    # 3) Dashboard animating — 24 frames spanning 0% → 100%
    metrics = synthesize_metrics(24)
    all_events = synthesize_events(60, working_estimate=metrics[-1]["working"])
    for i, m in enumerate(metrics):
        # Slide the event log forward as the run progresses.
        ev_window = all_events[: max(6, i * 2 + 4)]
        ev_window = ev_window[-6:]  # keep last 6
        frames.append(render_dashboard(
            pct=m["pct"],
            checked=m["checked"],
            total=m["total"],
            working=m["working"],
            hit=m["hit"],
            recent=m["recent"],
            cpm=m["cpm"],
            events=ev_window,
        ))
        # Front-half frames stay a beat longer so the eye reads them.
        durations.append(140 if i < 6 else (90 if i < 18 else 70))

    # 4) Final "done" hold frame
    frames.append(render_done(
        total_working=metrics[-1]["working"],
        saved_files=[
            "working_http_2026-10-18.txt",
            "working_socks5_2026-10-18.txt",
            "working_all_2026-10-18.json",
        ],
    ))
    durations.append(1600)

    out = Path("preview.gif")
    frames[0].save(
        out,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
    )
    return out, len(frames)


if __name__ == "__main__":
    out, frame_count = main()
    print(f"wrote {out} ({out.stat().st_size // 1024} KB, {frame_count} frames)")
