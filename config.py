"""
config.py - Central configuration for the Score Bug
"""
from dataclasses import dataclass, field
from typing import Optional

# ── Matrix hardware ───────────────────────────────────────────────────────────
MATRIX_COLS   = 128
MATRIX_ROWS   = 32
MATRIX_CHAIN  = 2
MATRIX_PARALLEL = 1

# rpi-rgb-led-matrix slowdown value (3 = Pi 4, use 4 if you see glitching)
GPIO_SLOWDOWN = 3

# ── Layout zones (in pixels) ──────────────────────────────────────────────────
# [LOGO_A | SCORE/INFO | LOGO_B]
LOGO_WIDTH    = 16   # pixels wide per team logo
LOGO_HEIGHT   = 16   # pixels tall per logo
LOGO_TOP_Y    = 2    # vertical offset for logo inside the display

CENTER_X_START = LOGO_WIDTH
CENTER_WIDTH   = MATRIX_COLS - (2 * LOGO_WIDTH)

# ── Colours (R, G, B) ─────────────────────────────────────────────────────────
COLOR_WHITE      = (255, 255, 255)
COLOR_BLACK      = (0,   0,   0)
COLOR_SCORE      = (255, 255, 255)
COLOR_CLOCK      = (255, 200,  50)
COLOR_LABEL      = (160, 160, 160)
COLOR_TIMEOUT    = (255, 140,   0)
COLOR_PENALTY    = (220,  50,  50)
COLOR_SEPARATOR  = ( 80,  80,  80)
COLOR_NO_GAME    = (100, 100, 100)
COLOR_SCROLL_IND = ( 50, 180, 255)

# ── ESPN API endpoints ────────────────────────────────────────────────────────
ESPN_ENDPOINTS = {
    "nfl": "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
    "nba": "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
}

# ── Team logo asset paths ─────────────────────────────────────────────────────
# Place 16x16 PNG logos in these directories, named by ESPN abbreviation
# e.g.  logos/nfl/KC.png, logos/nba/LAL.png
LOGO_DIR = {
    "nfl": "logos/nfl",
    "nba": "logos/nba",
}

# ── Fallback team colors when logo not found ──────────────────────────────────
# Format: "ABBR": (primary_R, primary_G, primary_B)
TEAM_COLORS = {
    # NFL
    "KC":  (227, 24,  55),   "PHI": ( 0, 76,  84),   "SF":  (170, 0,   0),
    "DAL": (  0, 53, 148),   "BUF": (  0, 51, 141),   "MIA": ( 0, 142, 151),
    "NE":  (  0, 34,  68),   "NYJ": ( 18, 87,  64),   "BAL": ( 26, 25,  95),
    "CIN": (251, 79,  20),   "CLE": ( 49, 29,  0 ),   "PIT": (255, 182,  18),
    "HOU": (  3, 32,  47),   "IND": (  0, 44, 95),    "JAX": (  9, 30,  66),
    "TEN": ( 75, 146, 219),  "DEN": (251, 79,  20),   "KC":  (227, 24,  55),
    "LV":  (165, 130,  82),  "LAC": (  0, 128, 198),  "SEA": (  0, 34, 68),
    "ARI": (151, 35,  63),   "LAR": (  0, 53, 148),   "GB":  ( 24, 48,  40),
    "MIN": ( 79, 38, 131),   "CHI": (  11, 22, 42),   "DET": (  0, 118, 182),
    "ATL": (167, 25,  48),   "CAR": (  0, 133, 202),  "NO":  (211, 188, 141),
    "TB":  (213, 10,  10),   "WAS": ( 63,  16,  16),  "NYG": ( 1, 35, 82),
    "PHI": (  0, 76,  84),   "DAL": (  0, 53, 148),
    # NBA
    "LAL": (85,  37, 130),   "GSW": (255, 199, 44),   "BOS": ( 0, 122,  51),
    "MIA": (152, 0,   46),   "CHI": (206,  17,  65),  "NY":  (0, 107, 182),
    "LAC": (200, 16,  46),   "MIL": ( 0,  71,  27),   "PHX": ( 29, 17, 96),
    "DEN": ( 13, 34,  64),   "MEM": ( 93, 118, 169),  "ATL": (225, 58,  62),
    "MIN": ( 12, 35,  64),   "DAL": (  0, 83, 188),   "BKN": (80, 80, 80),
    "CLE": (134, 0,   56),   "OKC": (  0, 125, 195),  "IND": (  0,  45, 98),
    "POR": (224, 58,  62),   "SA":   (196, 206, 211),  "ORL": (  0, 125, 197),
    "SAC": ( 91, 43, 130),   "HOU": (206, 17,  65),   "NOP": (  0,  22,  65),
    "CHA": (  0, 120, 140),  "TOR": (206, 17,  65),   "WSH": (0, 43, 92),
    "UTAH": (0,  43,  92),    "DET": (200, 16,  46),
}

@dataclass
class Config:
    sport: str            = "nfl"
    scroll: bool          = False
    game_index: Optional[int] = None
    scroll_dwell: int     = 10        # seconds per game in scroll mode
    refresh_interval: int = 30        # seconds between API calls
    brightness: int       = 60        # 0-100
    show_logos: bool      = True
