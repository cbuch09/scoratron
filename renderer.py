"""
renderer.py - Draws game state onto a 128x32 RGB LED matrix
(two 64x32 panels chained side by side).

Layout:
  Col 0-19:   Away team logo/color bar (20px)
  Col 20-107: Center info zone (88px)
  Col 108-127: Home team logo/color bar (20px)

Row layout:
  Row 0-6:   Team abbr + period label
  Row 7-18:  Big pixel scores + dash
  Row 19-23: Clock / status
  Row 24-27: Timeout dots
  Row 28-31: Fouls/penalties (live only)
"""

import time
import datetime
import os
from PIL import Image, ImageDraw, ImageFont
from models import GameState
from config import (
    Config,
    MATRIX_COLS, MATRIX_ROWS,
    COLOR_WHITE, COLOR_BLACK, COLOR_SCORE, COLOR_CLOCK,
    COLOR_LABEL, COLOR_TIMEOUT, COLOR_PENALTY, COLOR_SEPARATOR,
    COLOR_NO_GAME, COLOR_SCROLL_IND,
)

try:
    from rgbmatrix import RGBMatrix, RGBMatrixOptions
    HARDWARE_AVAILABLE = True
except ImportError:
    HARDWARE_AVAILABLE = False
    print("[renderer] rgbmatrix not found — preview mode")

FONT_DIR = os.path.join(os.path.dirname(__file__), "fonts")

def _load_pil_font(name):
    path = os.path.join(FONT_DIR, name)
    if os.path.exists(path):
        try:
            return ImageFont.load(path)
        except Exception as e:
            print(f"[font] Failed to load {path}: {e}")
    return ImageFont.load_default()

FONT = _load_pil_font("tom-thumb.pil")
FONT_ABBR = _load_pil_font("5x7.pil")

def _abbr_ink_width(font, text):
    """Total pixel width of text rendered with exactly 1px gaps between character ink."""
    total = 0
    for i, ch in enumerate(text):
        mask = font.getmask(ch)
        bbox = mask.getbbox()
        if bbox:
            total += bbox[2] - bbox[0]
        if i < len(text) - 1:
            total += 1  # 1px gap between chars
    return total

def _draw_abbr_tight(draw, font, text, anchor_x, y, color, align='left'):
    """Draw abbreviation with 1px gaps between actual ink. anchor_x is the
    left ink edge (align='left') or right ink edge (align='right')."""
    ink_w = _abbr_ink_width(font, text)
    cursor = anchor_x if align == 'left' else anchor_x - ink_w + 1
    for i, ch in enumerate(text):
        mask = font.getmask(ch)
        bbox = mask.getbbox()
        if bbox:
            ink_left = bbox[0]
            draw.text((cursor - ink_left, y), ch, font=font, fill=color)
            cursor += (bbox[2] - bbox[0])
        if i < len(text) - 1:
            cursor += 1

def text_width(text, font):
    try:
        bbox = font.getbbox(text)
        return bbox[2] - bbox[0]
    except Exception:
        return len(text) * 4

# ── Layout constants ──────────────────────────────────────────────────────────
BAR_W      = 20          # logo/color bar width each side
CX         = MATRIX_COLS // 2   # 64
LEFT_EDGE  = BAR_W               # 20
RIGHT_EDGE = MATRIX_COLS - BAR_W # 108

# Away score center and home score center
AWAY_CX = BAR_W + 22    # 42
HOME_CX = MATRIX_COLS - BAR_W - 22  # 86

# ── Big pixel digits (3-wide x 5-tall, drawn 2x2 = 6x10 per digit) ───────────
DIGITS = {
    '0': ["111","101","101","101","111"],
    '1': ["010","110","010","010","111"],
    '2': ["111","001","111","100","111"],
    '3': ["111","001","111","001","111"],
    '4': ["101","101","111","001","001"],
    '5': ["111","100","111","001","111"],
    '6': ["111","100","111","101","111"],
    '7': ["111","001","001","001","001"],
    '8': ["111","101","111","101","111"],
    '9': ["111","101","111","001","111"],
    '-': ["000","000","111","000","000"],
    '+': ["000","010","111","010","000"],
    '#': ["101","111","101","111","101"],
}

# 5×5 hash glyph — two horizontal bars with two vertical columns
HASH_5 = ["01010","11111","01010","11111","01010"]

def _seed_label_w(seed: int) -> int:
    """Pixel width of a seed label drawn by draw_seed_label: 5px(#) + 1gap + 3px per digit."""
    digits = len(str(seed))
    return 5 + 1 + digits * 4 - 1   # trailing gap on last digit not counted → -1

def draw_seed_label(draw, seed: int, x: int, y: int, color):
    """Draw seed as a 5×5 '#' then the digit(s) in the 3×5 micro font, 1px gap between."""
    # Draw '#' at 5px wide
    for ry, row in enumerate(HASH_5):
        for rx, bit in enumerate(row):
            if bit == '1':
                draw.point((x + rx, y + ry), fill=color)
    # Draw digit(s) 1px after the hash
    draw_micro_text(draw, str(seed), x + 5 + 1, y, color)

def draw_big_digit(draw, char, x, y, color):
    rows = DIGITS.get(char, DIGITS['-'])
    for ry, row in enumerate(rows):
        for rx, bit in enumerate(row):
            if bit == '1':
                px = x + rx * 2
                py = y + ry * 2
                draw.rectangle([px, py, px+1, py+1], fill=color)

# Micro font — same 3×5 bitmap as DIGITS but rendered 1×1 (3px wide, 5px tall)
def draw_micro_text(draw, text, x, y, color):
    """Draw a string using 1×1 pixel dots. Each char is 3px wide + 1px gap = 4px per char."""
    cx = x
    for ch in text:
        rows = DIGITS.get(ch, DIGITS['-'])
        for ry, row in enumerate(rows):
            for rx, bit in enumerate(row):
                if bit == '1':
                    draw.point((cx + rx, y + ry), fill=color)
        cx += 4  # 3px char + 1px gap

def draw_big_score(draw, score_str, cx, y, color):
    char_w = 8
    total_w = len(score_str) * char_w - 2
    x = cx - total_w // 2
    for ch in score_str:
        draw_big_digit(draw, ch, x, y, color)
        x += char_w


class ScoreBugRenderer:
    def __init__(self, config: Config):
        self.config = config
        self._matrix = None
        self._offscreen = None

        if HARDWARE_AVAILABLE:
            options = RGBMatrixOptions()
            options.rows             = MATRIX_ROWS   # 32
            options.cols             = 64            # one panel width
            options.chain_length     = 2             # two panels
            options.parallel         = 1
            options.gpio_slowdown    = 3
            options.hardware_mapping = "adafruit-hat"
            options.brightness       = config.brightness
            self._matrix    = RGBMatrix(options=options)
            self._offscreen = self._matrix.CreateFrameCanvas()
        else:
            self._preview_dir = "/tmp/scoratron_preview"
            os.makedirs(self._preview_dir, exist_ok=True)
            self._frame_count = 0

    # ── Public ────────────────────────────────────────────────────────────────

    def draw_game(self, game: GameState) -> Image.Image:
        img = self.render_game_image(game)
        self._push(img)
        return img

    def render_game_image(self, game: GameState) -> Image.Image:
        """Render a game to an Image without pushing to the matrix."""
        img  = self._new_image()
        draw = ImageDraw.Draw(img)
        self._draw_team_bars(img, draw, game)
        self._draw_header(draw, game)
        self._draw_team_labels(draw, game)
        self._draw_scores(draw, game)
        self._draw_clock(draw, game)
        if game.is_live:
            self._draw_timeouts(draw, game)
            self._draw_fouls(draw, game)
            self._draw_win_probability(draw, game)
            if game.sport == "nfl" and game.down_distance:
                self._draw_down_distance(draw, game)
        return img

    def draw_no_games(self, sport: str):
        img  = self._new_image()
        draw = ImageDraw.Draw(img)
        msg = f"No {sport.upper()} games right now"
        w = text_width(msg, FONT)
        draw.text((CX - w // 2, 13), msg, font=FONT, fill=COLOR_NO_GAME)
        self._push(img)

    # ── Weather icon primitives ────────────────────────────────────────────────

    @staticmethod
    def _wx_icon(draw, code, is_day, cx, cy):
        """Draw a ~14×14 weather icon centred at (cx, cy)."""
        SUN   = (255, 215, 0)
        MOON  = (200, 210, 255)
        CLOUD = (140, 150, 170)
        BLUE  = (70,  130, 255)
        WHITE = (220, 230, 255)
        DARK  = (70,   75,  95)
        BOLT  = (255, 220,  0)

        def sun(cx, cy, r=4):
            draw.ellipse([cx-r, cy-r, cx+r, cy+r], fill=SUN)
            for dx, dy in [(0,r+2),(0,-(r+2)),(r+2,0),(-(r+2),0),
                           (r+1,r+1),(r+1,-(r+1)),(-(r+1),r+1),(-(r+1),-(r+1))]:
                draw.point((cx+dx, cy+dy), fill=SUN)

        def moon(cx, cy):
            draw.ellipse([cx-4, cy-4, cx+4, cy+4], fill=MOON)
            draw.ellipse([cx-1, cy-4, cx+7, cy+4], fill=(0, 0, 0))

        def cloud(cx, cy, col=CLOUD):
            draw.ellipse([cx-5, cy-1, cx+0, cy+4], fill=col)
            draw.ellipse([cx-2, cy-3, cx+4, cy+3], fill=col)
            draw.rectangle([cx-5, cy+1, cx+4, cy+4], fill=col)

        def rain_drops(cx, cy):
            for rx in (-3, 0, 3):
                draw.point((cx+rx, cy+6), fill=BLUE)
                draw.point((cx+rx, cy+8), fill=BLUE)

        def snow_dots(cx, cy):
            for rx in (-3, 0, 3):
                draw.point((cx+rx,   cy+6), fill=WHITE)
                draw.point((cx+rx-1, cy+7), fill=WHITE)
                draw.point((cx+rx+1, cy+7), fill=WHITE)

        def fog_lines(cx, cy):
            for row in range(4):
                y = cy - 5 + row * 3
                draw.rectangle([cx-6, y, cx+6, y+1], fill=CLOUD)

        def bolt(cx, cy):
            # lightning bolt below cloud
            pts = [(cx+1,cy+1),(cx-1,cy+4),(cx+2,cy+4),(cx-2,cy+8)]
            for i in range(len(pts)-1):
                draw.line([pts[i], pts[i+1]], fill=BOLT, width=1)

        rain_codes  = {51,53,55,61,63,65,80,81,82}
        snow_codes  = {71,73,75,77,85,86}
        storm_codes = {95,96,99}
        fog_codes   = {45,48}

        if code in fog_codes:
            fog_lines(cx, cy)
        elif code in storm_codes:
            cloud(cx, cy-3, DARK)
            bolt(cx, cy-3)
        elif code in rain_codes:
            cloud(cx, cy-3)
            rain_drops(cx, cy-3)
        elif code in snow_codes:
            cloud(cx, cy-3)
            snow_dots(cx, cy-3)
        elif code == 3:
            cloud(cx, cy)
        elif code == 2:
            if is_day:
                sun(cx-1, cy-2, r=3)
            cloud(cx+1, cy+2)
        else:  # 0 or 1
            if is_day:
                sun(cx, cy)
            else:
                moon(cx, cy)

    def draw_weather(self, weather: dict):
        """Display current weather on the LED matrix.

        Layout: [TEMP] [ICON] [CONDITION]
                    [W:xx DIR  H:xx%  UV:x]
        """
        img  = self._new_image()
        draw = ImageDraw.Draw(img)

        temp_f    = str(weather.get('temp_f', '?'))
        condition = str(weather.get('condition', ''))[:16]
        humidity  = str(weather.get('humidity', '?'))
        wind_mph  = str(weather.get('wind_mph', '?'))
        wind_dir  = str(weather.get('wind_dir', ''))
        uv        = str(weather.get('uv_index', ''))
        code      = int(weather.get('weather_code', 0))
        is_day    = int(weather.get('is_day', 1))

        # Three rows centred in the 32px display:
        #   row 1 (FONT_ABBR, 7px): y=5, icon_cy=8
        #   row 2 (FONT,      5px): y=14
        #   row 3 (FONT,      5px): y=21
        # Total block = 7+2+5+2+5 = 21px → (32-21)//2 = 5

        # Temperature — FONT_ABBR, yellow
        temp_str = f"{temp_f}F"
        tw = text_width(temp_str, FONT_ABBR)
        draw.text((34, 7), temp_str, font=FONT_ABBR, fill=(255, 220, 80))

        # Icon — placed after temp with a small gap
        ICON_R  = 8          # bounding radius (rays / cloud extent)
        icon_cx = 34 + tw + 3 + ICON_R
        icon_cy = 8
        self._wx_icon(draw, code, is_day, icon_cx, icon_cy)

        # Condition — FONT_ABBR, vertically centred with icon
        cond_x = icon_cx + ICON_R + 3
        cond_y = icon_cy - 1   # FONT_ABBR is ~7px tall, dropped 2px from icon centre
        draw.text((cond_x, cond_y), condition, font=FONT_ABBR, fill=COLOR_WHITE)

        # Wind + humidity + UV — centred across full width
        wind_str = f"W:{wind_mph}"
        if wind_dir:
            wind_str += f" {wind_dir}"
        info = f"{wind_str}  H:{humidity}%"
        if uv and uv != '0':
            info += f"  UV:{uv}"
        iw = text_width(info, FONT)
        draw.text((CX - iw // 2, 15), info, font=FONT, fill=COLOR_CLOCK)

        # Time with seconds — centred
        time_str = datetime.datetime.now().strftime("%-I:%M:%S %p")
        tw2 = text_width(time_str, FONT)
        draw.text((CX - tw2 // 2, 22), time_str, font=FONT, fill=COLOR_WHITE)

        self._push(img)

    def draw_wifi_setup(self):
        """Show WiFi setup instructions on the LED matrix."""
        img  = self._new_image()
        draw = ImageDraw.Draw(img)
        line1 = "WiFi Setup"
        line2 = "Scoratron-Setup"
        line3 = "192.168.4.1"
        draw.text((CX - text_width(line1, FONT) // 2, 3),  line1, font=FONT, fill=(255, 140, 0))
        draw.text((CX - text_width(line2, FONT) // 2, 13), line2, font=FONT, fill=COLOR_WHITE)
        draw.text((CX - text_width(line3, FONT) // 2, 23), line3, font=FONT, fill=(80, 200, 80))
        self._push(img)

    def render_game_strip(self, games) -> Image.Image:
        """Stitch all game frames side-by-side for continuous scrolling."""
        strip = Image.new("RGB", (MATRIX_COLS * len(games), MATRIX_ROWS), (0, 0, 0))
        for i, game in enumerate(games):
            strip.paste(self.render_game_image(game), (i * MATRIX_COLS, 0))
        return strip

    def push_scroll_frame(self, strip: Image.Image, offset: int):
        """Crop one display-width window from strip at offset and push it, wrapping seamlessly."""
        strip_w = strip.width
        eff = offset % strip_w
        if eff + MATRIX_COLS <= strip_w:
            frame = strip.crop((eff, 0, eff + MATRIX_COLS, MATRIX_ROWS))
        else:
            remaining = strip_w - eff
            frame = Image.new("RGB", (MATRIX_COLS, MATRIX_ROWS), (0, 0, 0))
            frame.paste(strip.crop((eff, 0, strip_w, MATRIX_ROWS)), (0, 0))
            frame.paste(strip.crop((0, 0, MATRIX_COLS - remaining, MATRIX_ROWS)), (remaining, 0))
        self._push(frame)

    def animate_scroll_transition(self, old_img=None, new_img=None):
        """Smooth slide-left transition between games."""
        if old_img is None or new_img is None:
            return
        for offset in range(0, MATRIX_COLS + 1, 4):
            frame = self._new_image()
            # Old image slides out to the left
            if offset < MATRIX_COLS:
                frame.paste(old_img.crop((offset, 0, MATRIX_COLS, MATRIX_ROWS)), (0, 0))
            # New image slides in from the right
            frame.paste(new_img.crop((0, 0, offset, MATRIX_ROWS)),
                        (MATRIX_COLS - offset, 0))
            self._push(frame)
    
    def flash_score(self, game: GameState, scoring_team: str):
        """Flash just the scoring team's score 3 times."""
        if scoring_team == 'away':
            n = len(str(game.away.score))
            score_w = n * 8 - 2
            blank = [AWAY_CX - score_w // 2 - 1, 6, AWAY_CX + score_w - score_w // 2, 15]
        else:
            n = len(str(game.home.score))
            score_w = n * 8 - 2
            blank = [HOME_CX - score_w // 2 - 1, 6, HOME_CX + score_w - score_w // 2, 15]
        for flash in range(3):
            # Normal frame with score blanked out
            dark = self.render_game_image(game)
            dark_draw = ImageDraw.Draw(dark)
            dark_draw.rectangle(blank, fill=(0, 0, 0))
            self._push(dark)
            time.sleep(0.15)

            # Normal frame with score visible
            self._push(self.render_game_image(game))
            time.sleep(0.15)

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _draw_team_bars(self, img, draw, game):
        self._draw_team_bar(img, draw, game.away, 0)
        self._draw_team_bar(img, draw, game.home, MATRIX_COLS - BAR_W)

    def _draw_team_bar(self, img, draw, team, x):
        # Logo top 20px — logos are 18×18, centered with 1px top margin
        LOGO_W = 18
        if team.logo_path and os.path.exists(team.logo_path):
            try:
                logo = Image.open(team.logo_path).convert("RGB")
                if logo.size != (LOGO_W, LOGO_W):
                    logo = logo.resize((LOGO_W, LOGO_W), Image.NEAREST)
                logo_x = x + (BAR_W - LOGO_W) // 2
                img.paste(logo, (logo_x, 1))
            except Exception:
                draw.rectangle([x, 0, x+BAR_W-1, 19], fill=team.color)
        else:
            draw.rectangle([x, 0, x+BAR_W-1, 19], fill=team.color)

        # Team abbreviation rows 20-27.
        # 2-char abbrs are centered under the logo bar; 3-char abbrs are
        # anchored 3px from the nearest display edge.
        abbr = team.abbreviation[:3]
        is_home = (x != 0)
        if len(abbr) <= 2:
            ink_w = _abbr_ink_width(FONT_ABBR, abbr)
            bar_center = x + BAR_W // 2
            anchor = bar_center - ink_w // 2
            align = 'left'
        elif is_home:
            anchor, align = MATRIX_COLS - 1 - 3, 'right'
        else:
            anchor, align = 3, 'left'
        for dy in (-1, 1):
            _draw_abbr_tight(draw, FONT_ABBR, abbr, anchor, 20 + dy, COLOR_BLACK, align)
        for dx in (-1, 1):
            _draw_abbr_tight(draw, FONT_ABBR, abbr, anchor + dx, 20, COLOR_BLACK, align)
        _draw_abbr_tight(draw, FONT_ABBR, abbr, anchor, 20, COLOR_WHITE, align)

    def _draw_team_labels(self, draw, game):
        """Playoff: seed (#N) in team color. Regular season: W-L record in team color."""
        for team, bar_x, nudge in [
            (game.away, 0, 0),
            (game.home, MATRIX_COLS - BAR_W, 1),
        ]:
            r, g, b = team.color
            color = (r, g, b) if r + g + b >= 60 else (80, 80, 80)
            if game.is_playoff and team.seed:
                lw = _seed_label_w(team.seed)
                lx = bar_x + (BAR_W - lw) // 2 + nudge
                draw_seed_label(draw, team.seed, lx, 27, color)
            elif not game.is_playoff and team.record:
                label = team.record
                lw = (len(label) - 1) * 4 + 3
                lx = bar_x + (BAR_W - lw) // 2 + nudge
                draw_micro_text(draw, label, lx, 27, color)

    def _draw_header(self, draw, game):
        if game.is_halftime:
            label = "HALF"
            color = (255, 100, 0)
        elif game.is_ot:
            labels = {5:"OT", 6:"2OT", 7:"3OT"}
            label = labels.get(game.period, "OT")
            color = (180, 0, 255)
        elif game.is_live:
            labels = {1:"Q1", 2:"Q2", 3:"Q3", 4:"Q4"}
            label = labels.get(game.period, f"P{game.period}")
            color = COLOR_CLOCK
        elif game.status == "pre":
            label = game.sport.upper()
            color = COLOR_LABEL
        else:
            label = "FINAL"
            color = COLOR_CLOCK

        # Override with game label for special games (Super Bowl, Game 7 etc)
        game_label_active = game.is_playoff and game.game_label and not game.is_live
        if game_label_active:
            label = game.game_label[:8]
            color = (180, 0, 255)

        w = text_width(label, FONT)
        y = 0 if game_label_active else 1
        draw.text((CX - w//2, y), label, font=FONT, fill=color)

    def _draw_scores(self, draw, game):
        """Big pixel scores. Away left, home right, dash center."""
        if game.status == "pre":
            # Show VS instead of 0-0 for upcoming games
            vs_w = text_width("VS", FONT)
            draw.text((CX - vs_w // 2, 10), "VS", font=FONT, fill=COLOR_SEPARATOR)
            return

        draw_big_score(draw, str(game.away.score), AWAY_CX, 6, COLOR_SCORE)
        draw_big_digit(draw, '-', CX - 3, 6, COLOR_SEPARATOR)
        draw_big_score(draw, str(game.home.score), HOME_CX, 6, COLOR_SCORE)

        diff = abs(game.away.score - game.home.score)
        if diff > 0 and game.status in ('in', 'post'):
            diff_str = f"+{diff}"
            diff_w = (len(diff_str) - 1) * 4 + 3  # micro text pixel width
            # Diff sits 1px outside the winning team's score, bottom-aligned (y+4 = row 15)
            diff_y = 11
            if game.away.score > game.home.score:
                n = len(str(game.away.score))
                score_w = n * 8 - 2
                score_left = AWAY_CX - score_w // 2
                diff_x = score_left - diff_w - 1
            else:
                n = len(str(game.home.score))
                score_w = n * 8 - 2
                score_right = HOME_CX - score_w // 2 + score_w - 1
                diff_x = score_right + 2
            draw_micro_text(draw, diff_str, diff_x, diff_y, (0, 220, 80))

        if game.possession and game.is_live and game.sport == "nfl":
            # NFL only — possession dot below score of the team with the ball
            if game.possession == game.away.abbreviation:
                draw.rectangle([AWAY_CX - 1, 17, AWAY_CX + 1, 17], fill=COLOR_WHITE)
            elif game.possession == game.home.abbreviation:
                draw.rectangle([HOME_CX - 1, 17, HOME_CX + 1, 17], fill=COLOR_WHITE)

    def _draw_clock(self, draw, game):
        if game.status == "pre":
            # Show start time prominently for upcoming games
            time_str = (game.status_detail or "UPCOMING")[:12]
            w = text_width(time_str, FONT)
            draw.text((CX - w // 2, 17), time_str, font=FONT, fill=COLOR_CLOCK)
            return
        if game.is_halftime:
            if game.is_playoff and game.series_summary and game.sport == "nba":
                w = text_width(game.series_summary, FONT)
                draw.text((CX - w//2, 25), game.series_summary, font=FONT, fill=(180, 0, 255))
            return
        elif game.is_live:
            clock_str = game.clock
        elif game.status == "post":
            clock_str = ""
        else:
            clock_str = game.status_detail[:10] if game.status_detail else ""

        if clock_str:
            w = text_width(clock_str, FONT)
            draw.text((CX - w//2, 16), clock_str, font=FONT, fill=COLOR_CLOCK)

        # Show series record below clock during live NBA playoff games only
        if game.is_playoff and game.series_summary and game.is_live and game.sport == "nba":
            w = text_width(game.series_summary, FONT)
            draw.text((CX - w//2, 25), game.series_summary, font=FONT, fill=(180, 0, 255))

    def _draw_timeouts(self, draw, game):
        """Timeout dots — NFL only, ESPN doesn't provide NBA timeout data."""
        if game.sport != "nfl":
            return
        max_to  = 3
        y       = 22
        dot_w   = 3
        spacing = 5
        gap     = 6

        total_group_w = max_to * spacing - (spacing - dot_w)
        ax_start = AWAY_CX - total_group_w // 2
        for i in range(max_to):
            xi    = ax_start + i * spacing
            color = COLOR_TIMEOUT if i < game.away.timeouts else COLOR_SEPARATOR
            draw.rectangle([xi, y, xi+dot_w-1, y+2], fill=color)

        hx_start = HOME_CX - total_group_w // 2
        for i in range(max_to):
            xi    = hx_start + i * spacing
            color = COLOR_TIMEOUT if i < game.home.timeouts else COLOR_SEPARATOR
            draw.rectangle([xi, y, xi+dot_w-1, y+2], fill=color)

    def _draw_fouls(self, draw, game):
        """Penalty/foul counts — NFL only, ESPN doesn't provide NBA foul data."""
        if game.sport != "nfl":
            return
        y = 21
        draw.text((LEFT_EDGE - 2, y), str(game.away.fouls), font=FONT, fill=COLOR_PENALTY)
        home_str = str(game.home.fouls)
        hw = text_width(home_str, FONT)
        draw.text((RIGHT_EDGE - hw + 3, y), home_str, font=FONT, fill=COLOR_PENALTY)
        
    def _draw_down_distance(self, draw, game):
        """NFL down & distance below fouls."""
        dd = game.down_distance[:12].replace("&", "-") if game.down_distance else ""
        w = text_width(dd, FONT)
        draw.text((CX - w // 2, 26), dd, font=FONT, fill=COLOR_LABEL)

    def _draw_win_probability(self, draw, game):
        """1px probability bar at bottom, starting 1px after the last lit pixel of each
        team's record/seed label."""
        if not game.is_live:
            return

        def _label_w(team):
            if game.is_playoff and team.seed:
                return _seed_label_w(team.seed)
            return (len(team.record) - 1) * 4 + 3 if team.record else 0

        away_lw = _label_w(game.away)
        home_lw = _label_w(game.home)

        if away_lw:
            lx = (BAR_W - away_lw) // 2
            bar_start = lx + away_lw + 1     # 1px gap after last lit pixel
        else:
            bar_start = LEFT_EDGE

        if home_lw:
            lx = (MATRIX_COLS - BAR_W) + (BAR_W - home_lw) // 2 + 1  # nudge=1
            bar_end = lx - 2                 # 1px gap before first lit pixel
        else:
            bar_end = RIGHT_EDGE - 1

        total_w = bar_end - bar_start + 1
        if total_w <= 0:
            return
        away_w = round(total_w * game.away_win_pct)
        home_w = total_w - away_w
        y = 31

        if away_w > 1:
            draw.rectangle([bar_start, y, bar_start + away_w - 2, y], fill=game.away.color)
        draw.rectangle([bar_start + away_w - 1, y, bar_start + away_w - 1, y], fill=(0, 0, 0))
        if home_w > 0:
            draw.rectangle([bar_start + away_w, y, bar_start + away_w + home_w - 1, y], fill=game.home.color)

    # ── Matrix output ─────────────────────────────────────────────────────────

    def _new_image(self):
        return Image.new("RGB", (MATRIX_COLS, MATRIX_ROWS), (0, 0, 0))

    def _push(self, img):
        if HARDWARE_AVAILABLE and self._matrix:
            self._offscreen.SetImage(img)
            self._offscreen = self._matrix.SwapOnVSync(self._offscreen)
        else:
            path = os.path.join(self._preview_dir, f"frame_{self._frame_count:05d}.png")
            preview = img.resize((MATRIX_COLS * 6, MATRIX_ROWS * 6), Image.NEAREST)
            preview.save(path)
            self._frame_count += 1
            if self._frame_count % 20 == 0:
                print(f"[preview] frame {self._frame_count} -> {self._preview_dir}")