"""
score_fetcher.py - Pulls live/recent scores from ESPN's unofficial API.
No API key required. Parses NFL and NBA game data into GameState objects.
"""

import requests
import os
from datetime import datetime, timezone, timedelta

from typing import List, Optional
from models import GameState, TeamInfo
from config import Config, ESPN_ENDPOINTS, TEAM_COLORS, LOGO_DIR

REQUEST_TIMEOUT = 10   # seconds

_SEED_ENDPOINTS = {
    # seasontype=2 (regular season) gives the accurate pre-playoff bracket seeds.
    # seasontype=3 (playoff) recalculates standings and produces wrong values.
    'nba': 'https://site.api.espn.com/apis/v2/sports/basketball/nba/standings?seasontype=2',
    'nfl': 'https://site.api.espn.com/apis/v2/sports/football/nfl/standings?seasontype=2',
}
_seed_cache: dict = {}   # {sport: {team_abbr: seed}}

def _fetch_playoff_seeds(sport: str, session) -> dict:
    """Return {abbr: seed} for current playoff teams. Cached for the session."""
    if sport in _seed_cache:
        return _seed_cache[sport]
    url = _SEED_ENDPOINTS.get(sport)
    if not url:
        return {}
    try:
        r = session.get(url, timeout=REQUEST_TIMEOUT, verify='/etc/ssl/certs/ca-certificates.crt')
        r.raise_for_status()
        seeds = {}
        for conf in r.json().get('children', []):
            for entry in conf.get('standings', {}).get('entries', []):
                abbr = entry.get('team', {}).get('abbreviation', '')
                for stat in entry.get('stats', []):
                    if stat.get('name') == 'playoffSeed':
                        val = stat.get('value')
                        if val:
                            seeds[abbr] = int(val)
        _seed_cache[sport] = seeds
        return seeds
    except Exception as e:
        print(f'[fetcher] seed fetch error: {e}')
        return {}

class ScoreFetcher:
    def __init__(self, config: Config):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; ScoreBug/1.0)"
        })

    def fetch_games(self) -> Optional[List[GameState]]:
        url = ESPN_ENDPOINTS[self.config.sport]
        try:
            resp = self.session.get(url, timeout=REQUEST_TIMEOUT, verify='/etc/ssl/certs/ca-certificates.crt')
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            print(f"[fetcher] Network error: {e}")
            return None
        except ValueError as e:
            print(f"[fetcher] JSON parse error: {e}")
            return None

        events = data.get("events", [])
        if not events:
            print(f"[fetcher] No events for {self.config.sport} — off-season")
            return None
        games = []
        for event in events:
            game = self._parse_event(event)
            if game:
                games.append(game)

        # Sort: live games first, then upcoming, then final
        def sort_key(g):
            if g.is_live:
                return 0
            if g.status == "pre":
                return 1
            return 2

        games.sort(key=sort_key)

        # Priority: live → recent finished → upcoming
        live = [g for g in games if g.is_live]
        if live:
            return live

        # No live games — show all finished games so the display can scroll through them
        finished = [g for g in games if g.status == "post"]
        if finished:
            non_stale = [g for g in finished if g.sport == "nba" or not g.is_playoff]
            if non_stale:
                return non_stale

        # No live or recent finished — show upcoming games within 60 minutes
        upcoming = [g for g in games if g.status == "pre"]
        if upcoming:
            now_utc = datetime.now(timezone.utc)
            cutoff  = now_utc + timedelta(minutes=60)
            def starts_soon(g):
                if not g.start_time_utc:
                    return True
                try:
                    t = datetime.fromisoformat(g.start_time_utc.replace("Z", "+00:00"))
                    return t <= cutoff
                except Exception:
                    return True
            upcoming = [g for g in upcoming if starts_soon(g)]
            if upcoming:
                return upcoming

        return []

    def _parse_event(self, event: dict) -> Optional[GameState]:
        try:
            game_id    = event.get("id", "unknown")
            sport      = self.config.sport
            status_obj = event.get("status", {})
            status_type = status_obj.get("type", {})
            state      = status_type.get("state", "pre")   # "pre", "in", "post"
            detail     = status_obj.get("type", {}).get("shortDetail", "")

            # For upcoming games, convert the UTC start time to local system time
            if state == "pre":
                utc_str = event.get("date", "")
                if utc_str:
                    try:
                        utc_dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
                        local_dt = utc_dt.astimezone()  # uses Pi's /etc/localtime
                        detail = local_dt.strftime("%-I:%M %p")  # e.g. "7:30 PM"
                    except Exception:
                        pass  # fall back to ESPN's shortDetail
            period     = status_obj.get("period", 0)
            clock      = status_obj.get("displayClock", "0:00")
            # Detect halftime
            detail_text = status_type.get("shortDetail", "")
            is_halftime = (state == "in" and "halftime" in detail_text.lower())
            is_ot = (state == "in" and period > 4 and sport == "nba") or \
                    (state == "in" and period > 4 and sport == "nfl")
            is_live    = (state == "in")

            competitions = event.get("competitions", [])
            if not competitions:
                return None
            comp = competitions[0]

            competitors = comp.get("competitors", [])
            if len(competitors) < 2:
                return None

            home = away = None
            home_comp = away_comp = {}
            for c in competitors:
                team_data = c.get("team", {})
                abbr  = team_data.get("abbreviation", "UNK")
                name  = team_data.get("displayName", "Unknown")
                score = int(c.get("score", 0) or 0)

                # Timeouts
                if sport == "nfl":
                    timeouts = c.get("timeouts", 3)
                else:
                    timeouts = 0  # ESPN doesn't provide NBA timeout data

                # NFL penalties / NBA team fouls
                fouls = 0
                stats = c.get("statistics", [])
                for stat in stats:
                    if sport == "nfl" and stat.get("name") == "totalPenaltiesYards":
                        fouls = int(stat.get("displayValue", "0-0").split("-")[0])

                color = TEAM_COLORS.get(abbr, (128, 128, 128))
                logo_path = self._logo_path(abbr)

                record = ""
                for rec in c.get("records", []):
                    if rec.get("name") == "overall":
                        record = rec.get("summary", "")
                        break

                playoff_seeds = _fetch_playoff_seeds(self.config.sport, self.session)
                seed = playoff_seeds.get(abbr, 0)

                team = TeamInfo(
                    name=name,
                    abbreviation=abbr,
                    score=score,
                    timeouts=timeouts,
                    fouls=fouls,
                    logo_path=logo_path,
                    color=color,
                    record=record,
                    seed=seed,
                )

                if c.get("homeAway") == "home":
                    home = team
                    home_comp = c
                else:
                    away = team
                    away_comp = c

            if not home or not away:
                return None

            # Possession — NFL has explicit possession field, NBA inferred from lastPlay
            possession = None
            down_distance = None
            situation = comp.get("situation", {})
            if sport == "nfl" and is_live:
                poss_team = situation.get("possession", {})
                if isinstance(poss_team, dict):
                    possession = poss_team.get("abbreviation")
                elif isinstance(poss_team, str):
                    possession = poss_team
                down = situation.get("down")
                distance = situation.get("distance")
                if down:
                    down_str = {1:"1st",2:"2nd",3:"3rd",4:"4th"}.get(down, str(down))
                    down_distance = f"{down_str}-{distance}"
            elif sport == "nba" and is_live:
                last_play = situation.get("lastPlay", {})
                poss_team_id = last_play.get("team", {}).get("id")
                if poss_team_id:
                    for c in competitors:
                        if str(c.get("team", {}).get("id")) == str(poss_team_id):
                            possession = c.get("team", {}).get("abbreviation")
                            break

            # Playoff detection
            season = event.get("season", {})
            is_playoff = season.get("type") == 3 or season.get("slug") == "post-season"

            # Series record — data lives on competition, not event
            series_summary = ""
            game_label = ""
            series = comp.get("series", {}) or event.get("series", {})
            if series and is_playoff:
                # Match series wins by team ID — order varies, don't assume away/home
                wins_by_id = {str(s["id"]): s.get("wins", 0) for s in series.get("competitors", [])}
                away_id = str(away_comp.get("team", {}).get("id", ""))
                home_id = str(home_comp.get("team", {}).get("id", ""))
                away_wins = wins_by_id.get(away_id, 0)
                home_wins = wins_by_id.get(home_id, 0)
                total = away_wins + home_wins
                if away_wins == home_wins:
                    series_summary = f"Tied {away_wins}-{home_wins}"
                elif away_wins > home_wins:
                    series_summary = f"{away.abbreviation} leads {away_wins}-{home_wins}"
                else:
                    series_summary = f"{home.abbreviation} leads {home_wins}-{away_wins}"
                game_label = f"Game {total + 1}" if total < 7 else "Game 7"

            # Check notes for named games like Super Bowl
            notes = comp.get("notes", [])
            for note in notes:
                headline = note.get("headline", "")
                if headline:
                    game_label = headline[:14]  # truncate to fit display
                    break

            # Win probability
            away_win_pct = 0.5
            home_win_pct = 0.5
            if is_live:
                last_play = situation.get("lastPlay", {})
                prob = last_play.get("probability", {})
                if prob:
                    away_win_pct = float(prob.get("awayWinPercentage", 0.5))
                    home_win_pct = float(prob.get("homeWinPercentage", 0.5))

            return GameState(
                game_id=game_id,
                sport=sport,
                status=state,
                status_detail=detail,
                period=period,
                clock=clock,
                home=home,
                away=away,
                is_live=is_live,
                possession=possession,
                down_distance=down_distance,
                is_halftime=is_halftime,
                is_ot=is_ot,
                is_playoff=is_playoff,
                series_summary=series_summary,
                game_label=game_label,
                away_win_pct=away_win_pct,
                home_win_pct=home_win_pct,
                start_time_utc=event.get("date", ""),
            )

        except (KeyError, TypeError, ValueError) as e:
            print(f"[fetcher] Parse error for event: {e}")
            return None

    def _logo_path(self, abbreviation: str) -> Optional[str]:
        """Returns path to team logo PNG if it exists, else None."""
        if not self.config.show_logos:
            return None
        logo_dir = LOGO_DIR.get(self.config.sport, "logos")
        path = os.path.join(logo_dir, f"{abbreviation}.png")
        return path if os.path.exists(path) else None
