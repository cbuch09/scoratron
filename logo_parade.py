#!/usr/bin/env python3
"""
logo_parade.py - Smoothly scrolls all team logos across the LED matrix.
Can be triggered from the web UI or run standalone.

Usage:
    sudo ~/rgbmatrix/bin/python3 logo_parade.py --sport nfl
    sudo ~/rgbmatrix/bin/python3 logo_parade.py --sport nba
    sudo ~/rgbmatrix/bin/python3 logo_parade.py --sport both
"""

import argparse
import os
import sys
import time
import signal

sys.path.insert(0, '/home/admin/scoratron')
os.chdir('/home/admin/scoratron')

from PIL import Image, ImageDraw, ImageFont
from config import MATRIX_COLS, MATRIX_ROWS, TEAM_COLORS

try:
    from rgbmatrix import RGBMatrix, RGBMatrixOptions
    HARDWARE_AVAILABLE = True
except ImportError:
    HARDWARE_AVAILABLE = False
    print("[parade] Preview mode")

FONT_DIR = os.path.join(os.path.dirname(__file__), "fonts")

def _load_font(name):
    path = os.path.join(FONT_DIR, name)
    if os.path.exists(path):
        try:
            return ImageFont.load(path)
        except Exception:
            pass
    return ImageFont.load_default()

FONT = _load_font("5x7.pil")

NFL_TEAMS = [
    "ARI","ATL","BAL","BUF","CAR","CHI","CIN","CLE","DAL","DEN",
    "DET","GB","HOU","IND","JAX","KC","LAC","LAR","LV","MIA",
    "MIN","NE","NO","NYG","NYJ","PHI","PIT","SEA","SF","TB",
    "TEN","WAS"
]

NBA_TEAMS = [
    "ATL","BKN","BOS","CHA","CHI","CLE","DAL","DEN","DET","GS",
    "HOU","IND","LAC","LAL","MEM","MIA","MIL","MIN","NO","NY",
    "OKC","ORL","PHI","PHX","POR","SA","SAC","TOR","UTAH","WSH"
]

LOGO_SIZE    = 24   # px — slightly larger than matrix logos for better visibility
LOGO_SPACING = 8    # px gap between logos
ITEM_WIDTH   = LOGO_SIZE + LOGO_SPACING
LABEL_Y      = LOGO_SIZE + 2   # row where abbreviation text sits
SCROLL_SPEED = 1    # pixels per frame
FRAME_DELAY  = 0.03 # seconds per frame (~33fps)


def load_logo(abbr, sport):
    """Load a logo, return as RGB PIL image or a colored placeholder."""
    path = f"logos/{sport}/{abbr}.png"
    if os.path.exists(path):
        try:
            img = Image.open(path).convert("RGB")
            if img.size != (LOGO_SIZE, LOGO_SIZE):
                img = img.resize((LOGO_SIZE, LOGO_SIZE), Image.NEAREST)
            return img
        except Exception:
            pass
    # Fallback: colored block with abbreviation
    color = TEAM_COLORS.get(abbr, (80, 80, 80))
    img = Image.new("RGB", (LOGO_SIZE, LOGO_SIZE), color)
    draw = ImageDraw.Draw(img)
    abbr_short = abbr[:3]
    try:
        bbox = FONT.getbbox(abbr_short)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
    except Exception:
        tw, th = len(abbr_short) * 5, 7
    draw.text(((LOGO_SIZE - tw) // 2, (LOGO_SIZE - th) // 2),
              abbr_short, font=FONT, fill=(255, 255, 255))
    return img


def build_parade_strip(teams, sport):
    """Build a wide image with all logos laid out side by side."""
    total_width = len(teams) * ITEM_WIDTH + MATRIX_COLS
    strip = Image.new("RGB", (total_width, MATRIX_ROWS), (0, 0, 0))
    draw  = ImageDraw.Draw(strip)

    for i, abbr in enumerate(teams):
        x = i * ITEM_WIDTH + MATRIX_COLS  # start offscreen right
        logo = load_logo(abbr, sport)

        # Center logo vertically in top portion
        logo_y = (LOGO_SIZE - LOGO_SIZE) // 2   # = 0
        strip.paste(logo, (x, logo_y))

        # Draw abbreviation below logo
        try:
            bbox = FONT.getbbox(abbr)
            tw = bbox[2] - bbox[0]
        except Exception:
            tw = len(abbr) * 5
        tx = x + (LOGO_SIZE - tw) // 2
        color = TEAM_COLORS.get(abbr, (160, 160, 160))
        # Lighten very dark colors for readability
        r, g, b = color
        if r + g + b < 60:
            color = (120, 120, 120)
        draw.text((tx, LABEL_Y), abbr, font=FONT, fill=color)

    return strip, total_width


def run_parade(sport="nba", brightness=60, loop=True):
    """Run the logo parade on the matrix."""

    if HARDWARE_AVAILABLE:
        options = RGBMatrixOptions()
        options.rows             = MATRIX_ROWS
        options.cols             = 64
        options.chain_length     = 2
        options.parallel         = 1
        options.gpio_slowdown    = 3
        options.hardware_mapping = "adafruit-hat"
        options.brightness       = brightness
        matrix   = RGBMatrix(options=options)
        canvas   = matrix.CreateFrameCanvas()
    else:
        preview_dir = "/tmp/parade_preview"
        os.makedirs(preview_dir, exist_ok=True)
        frame_count = [0]

    if sport == "both":
        teams = NFL_TEAMS + NBA_TEAMS
        sport_dir = "nfl"   # will override per team below
    elif sport == "nfl":
        teams = NFL_TEAMS
        sport_dir = "nfl"
    else:
        teams = NBA_TEAMS
        sport_dir = "nba"

    # For "both" mode, tag each team with its sport
    if sport == "both":
        tagged = [(t, "nfl") for t in NFL_TEAMS] + [(t, "nba") for t in NBA_TEAMS]
    else:
        tagged = [(t, sport_dir) for t in teams]

    # Build strip — logos start at x=0, seamless wrap copy appended at end
    loop_width  = len(tagged) * ITEM_WIDTH          # pixels before seamless repeat
    total_width = loop_width + MATRIX_COLS           # extra copy for smooth wrap
    strip = Image.new("RGB", (total_width, MATRIX_ROWS), (0, 0, 0))
    draw  = ImageDraw.Draw(strip)

    for i, (abbr, sp) in enumerate(tagged):
        x    = i * ITEM_WIDTH
        logo = load_logo(abbr, sp)
        strip.paste(logo, (x, 0))

        try:
            bbox = FONT.getbbox(abbr)
            tw   = bbox[2] - bbox[0]
        except Exception:
            tw = len(abbr) * 5
        tx    = x + (LOGO_SIZE - tw) // 2
        color = TEAM_COLORS.get(abbr, (160, 160, 160))
        r, g, b = color
        if r + g + b < 60:
            color = (120, 120, 120)
        draw.text((tx, LABEL_Y), abbr, font=FONT, fill=color)

    # Copy first MATRIX_COLS pixels to end so looping is seamless
    strip.paste(strip.crop((0, 0, MATRIX_COLS, MATRIX_ROWS)), (loop_width, 0))

    print(f"[parade] {len(tagged)} logos loaded, strip width={total_width}px")
    print("[parade] Scrolling — Ctrl+C to stop")

    offset = 0
    running = True

    def stop(sig, frame):
        nonlocal running
        running = False
        print("\n[parade] Stopping...")

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    while running:
        # Crop current view from strip
        frame = strip.crop((offset, 0, offset + MATRIX_COLS, MATRIX_ROWS))

        if HARDWARE_AVAILABLE:
            canvas.SetImage(frame)
            canvas = matrix.SwapOnVSync(canvas)
        else:
            path = f"/tmp/parade_preview/frame_{frame_count[0]:05d}.png"
            frame.resize((MATRIX_COLS * 4, MATRIX_ROWS * 4), Image.NEAREST).save(path)
            frame_count[0] += 1

        offset += SCROLL_SPEED

        # Loop: wrap back seamlessly once we've passed the full logo sequence
        if offset >= loop_width:
            if loop:
                offset -= loop_width   # seamless: no black gap
            else:
                break

        time.sleep(FRAME_DELAY)

    if HARDWARE_AVAILABLE:
        matrix.Clear()


def run_parade_on_matrix(matrix, canvas, sport="nba", stop_fn=None):
    """
    Run the logo parade using an already-initialised RGBMatrix + canvas.
    stop_fn() is called each frame; returning True exits the loop.
    Used by main.py to keep a single RGBMatrix instance active.
    """
    if sport == "both":
        tagged = [(t, "nfl") for t in NFL_TEAMS] + [(t, "nba") for t in NBA_TEAMS]
    elif sport == "nfl":
        tagged = [(t, "nfl") for t in NFL_TEAMS]
    else:
        tagged = [(t, "nba") for t in NBA_TEAMS]

    loop_width  = len(tagged) * ITEM_WIDTH
    total_width = loop_width + MATRIX_COLS
    strip = Image.new("RGB", (total_width, MATRIX_ROWS), (0, 0, 0))
    draw  = ImageDraw.Draw(strip)

    for i, (abbr, sp) in enumerate(tagged):
        x    = i * ITEM_WIDTH
        logo = load_logo(abbr, sp)
        strip.paste(logo, (x, 0))
        try:
            bbox = FONT.getbbox(abbr)
            tw   = bbox[2] - bbox[0]
        except Exception:
            tw = len(abbr) * 5
        tx    = x + (LOGO_SIZE - tw) // 2
        color = TEAM_COLORS.get(abbr, (160, 160, 160))
        r, g, b = color
        if r + g + b < 60:
            color = (120, 120, 120)
        draw.text((tx, LABEL_Y), abbr, font=FONT, fill=color)

    # Seamless wrap: copy first MATRIX_COLS pixels to the end
    strip.paste(strip.crop((0, 0, MATRIX_COLS, MATRIX_ROWS)), (loop_width, 0))

    offset = 0
    while True:
        if stop_fn and stop_fn():
            break
        frame  = strip.crop((offset, 0, offset + MATRIX_COLS, MATRIX_ROWS))
        canvas.SetImage(frame)
        canvas = matrix.SwapOnVSync(canvas)
        offset = (offset + SCROLL_SPEED) % loop_width
        time.sleep(FRAME_DELAY)

    matrix.Clear()
    return canvas   # caller may need the swapped canvas reference


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Logo Parade")
    parser.add_argument("--sport", choices=["nfl", "nba", "both"], default="nba")
    parser.add_argument("--brightness", type=int, default=60)
    parser.add_argument("--no-loop", action="store_true")
    args = parser.parse_args()
    run_parade(sport=args.sport, brightness=args.brightness, loop=not args.no_loop)