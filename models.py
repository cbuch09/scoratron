"""
models.py - Data classes for game state
"""
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class TeamInfo:
    name: str               # Full name e.g. "Kansas City Chiefs"
    abbreviation: str       # Short e.g. "KC"
    score: int = 0
    timeouts: int = 3       # Remaining timeouts (NFL: 3, NBA: varies)
    fouls: int = 0          # NBA fouls / NFL penalties this game
    logo_path: Optional[str] = None
    color: tuple = (128, 128, 128)   # Fallback RGB
    record: str = ""                 # e.g. "24-8" (wins-losses)
    seed: int = 0                    # playoff seed (0 = unknown/regular season)

@dataclass
class GameState:
    game_id: str
    sport: str              # "nfl" or "nba"
    status: str             # "pre", "in", "post"
    status_detail: str      # e.g. "Q3 8:42", "Halftime", "Final"
    period: int             # Quarter (NFL/NBA) or half
    clock: str              # Remaining clock e.g. "8:42"
    home: TeamInfo
    away: TeamInfo
    is_live: bool = False
    possession: Optional[str] = None   # abbreviation of team with ball (NFL)
    down_distance: Optional[str] = None  # e.g. "3rd & 7" (NFL only)
    is_halftime: bool = False
    is_ot: bool = False
    is_playoff: bool = False
    series_summary: str = ""   # e.g. "BOS leads 2-1" or "Tied 2-2"
    game_label: str = ""       # e.g. "Super Bowl LX" or "Game 5"
    away_win_pct: float = 0.5
    home_win_pct: float = 0.5
    start_time_utc: str = ""   # ISO-8601 UTC, used to filter upcoming games
