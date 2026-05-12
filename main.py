#!/usr/bin/env python3
import argparse
import time
import sys
import signal
import os
import json
import requests
from datetime import datetime, timezone
from renderer import ScoreBugRenderer
from score_fetcher import ScoreFetcher
from config import Config
from models import GameState, TeamInfo

def signal_handler(sig, frame):
    print("\nShutting down...")
    sys.exit(0)

def write_preview(game):
    """Write current game state to a file for the web UI to read."""
    try:
        data = {
            'game_id': game.game_id,
            'sport': game.sport,
            'status': game.status,
            'status_detail': game.status_detail,
            'period': game.period,
            'clock': game.clock,
            'is_live': game.is_live,
            'is_halftime': game.is_halftime,
            'is_ot': game.is_ot,
            'is_playoff': game.is_playoff,
            'series_summary': game.series_summary,
            'game_label': game.game_label,
            'possession': game.possession,
            'down_distance': game.down_distance,
            'away_win_pct': game.away_win_pct,
            'home_win_pct': game.home_win_pct,
            'away': {
                'name': game.away.name,
                'abbreviation': game.away.abbreviation,
                'score': game.away.score,
                'timeouts': game.away.timeouts,
                'fouls': game.away.fouls,
                'color': list(game.away.color),
                'record': game.away.record,
                'seed': game.away.seed,
            },
            'home': {
                'name': game.home.name,
                'abbreviation': game.home.abbreviation,
                'score': game.home.score,
                'timeouts': game.home.timeouts,
                'fouls': game.home.fouls,
                'color': list(game.home.color),
                'record': game.home.record,
                'seed': game.home.seed,
            },
        }
        with open('/tmp/scoratron_current.json', 'w') as f:
            json.dump(data, f)
    except Exception as e:
        print(f'[preview] write error: {e}')

def write_weather_preview(weather):
    """Write current weather state to the preview file for the web UI."""
    import datetime
    try:
        data = dict(weather)
        data['mode'] = 'weather'
        data['time'] = datetime.datetime.now().strftime("%-I:%M:%S %p")
        with open('/tmp/scoratron_current.json', 'w') as f:
            json.dump(data, f)
    except Exception as e:
        print(f'[preview] weather write error: {e}')

def game_started_within(game, seconds):
    """Return True if the game's start time is within the last `seconds` seconds."""
    if not game.start_time_utc:
        return True  # unknown start time — assume recent
    try:
        start = datetime.fromisoformat(game.start_time_utc.replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - start).total_seconds()
        return age < seconds
    except Exception:
        return True

def load_webui_settings():
    path = '/home/admin/scoratron/settings.json'
    try:
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
    except Exception as e:
        print(f'[settings] load error: {e}')
    return None

def load_wifi_setup_active():
    path = '/tmp/scoratron_wifi_setup.json'
    try:
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f).get('active', False)
    except Exception:
        pass
    return False

def load_parade_active():
    path = '/tmp/scoratron_parade.json'
    try:
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f).get('active', False)
    except Exception:
        pass
    return False

_weather_cache = {'data': None, 'last_fetch': 0}
WEATHER_TTL = 900  # 15 minutes

_WMO_CODES = {
    0:'Clear', 1:'Mostly Clear', 2:'Partly Cloudy', 3:'Overcast',
    45:'Fog', 48:'Icy Fog',
    51:'Light Drizzle', 53:'Drizzle', 55:'Heavy Drizzle',
    61:'Light Rain', 63:'Rain', 65:'Heavy Rain',
    71:'Light Snow', 73:'Snow', 75:'Heavy Snow', 77:'Snow Grains',
    80:'Light Showers', 81:'Showers', 82:'Heavy Showers',
    85:'Snow Showers', 86:'Heavy Snow Showers',
    95:'Thunderstorm', 96:'T-Storm+Hail', 99:'T-Storm+Hail',
}
_CERT = '/etc/ssl/certs/ca-certificates.crt'

def _wind_dir(deg):
    dirs = ['N','NE','E','SE','S','SW','W','NW']
    return dirs[round(deg / 45) % 8]

def _fetch_weather_at(lat, lon, label):
    """Fetch weather from open-meteo for the given coordinates. Returns data dict or None."""
    try:
        wx = requests.get(
            'https://api.open-meteo.com/v1/forecast',
            params={
                'latitude': lat, 'longitude': lon,
                'current': ('temperature_2m,apparent_temperature,relative_humidity_2m,'
                            'weather_code,wind_speed_10m,wind_direction_10m,uv_index,is_day'),
                'temperature_unit': 'fahrenheit',
                'wind_speed_unit': 'mph',
                'forecast_days': 1,
            },
            timeout=10, verify=_CERT,
        )
        wx.raise_for_status()
        cur = wx.json()['current']
        code = int(cur.get('weather_code', 0))
        return {
            'temp_f':       str(round(cur['temperature_2m'])),
            'feels_like_f': str(round(cur['apparent_temperature'])),
            'condition':    _WMO_CODES.get(code, f'Code {code}'),
            'humidity':     str(round(cur['relative_humidity_2m'])),
            'wind_mph':     str(round(cur['wind_speed_10m'])),
            'wind_dir':     _wind_dir(cur.get('wind_direction_10m', 0)),
            'uv_index':     str(round(cur.get('uv_index', 0))),
            'is_day':       int(cur.get('is_day', 1)),
            'weather_code': code,
            'zip_code':     label,
        }
    except Exception as e:
        print(f'[weather] fetch error: {e}')
        return None

def get_weather(zip_code):
    now = time.time()
    if now - _weather_cache['last_fetch'] < WEATHER_TTL and _weather_cache['data']:
        return _weather_cache['data']
    try:
        geo = requests.get(
            'https://geocoding-api.open-meteo.com/v1/search',
            params={'name': zip_code, 'count': 1, 'format': 'json'},
            timeout=10, verify=_CERT,
        )
        geo.raise_for_status()
        results = geo.json().get('results')
        if not results:
            print(f'[weather] zip {zip_code!r} not found')
            return _weather_cache['data']
        lat = results[0]['latitude']
        lon = results[0]['longitude']
        data = _fetch_weather_at(lat, lon, zip_code)
        if data:
            _weather_cache['data'] = data
            _weather_cache['last_fetch'] = now
        return _weather_cache['data']
    except Exception as e:
        print(f'[weather] fetch error: {e}')
        return _weather_cache['data']

def get_weather_by_ip():
    """Geolocate via public IP and fetch weather. Uses the same cache as get_weather()."""
    now = time.time()
    if now - _weather_cache['last_fetch'] < WEATHER_TTL and _weather_cache['data']:
        return _weather_cache['data']
    try:
        geo = requests.get('https://ipapi.co/json/', timeout=10, verify=_CERT)
        geo.raise_for_status()
        info = geo.json()
        lat = info.get('latitude')
        lon = info.get('longitude')
        if lat is None or lon is None:
            print('[weather] IP geolocation returned no coordinates')
            return _weather_cache['data']
        city = info.get('city', '')
        label = city or 'Auto'
        data = _fetch_weather_at(lat, lon, label)
        if data:
            _weather_cache['data'] = data
            _weather_cache['last_fetch'] = now
        return _weather_cache['data']
    except Exception as e:
        print(f'[weather] IP geolocation error: {e}')
        return _weather_cache['data']

def load_sim_game():
    path = '/tmp/scoratron_sim.json'
    try:
        if os.path.exists(path):
            with open(path) as f:
                content = f.read().strip()
                if not content:
                    return None
                data = json.loads(content)
                return data if data.get('active') else None
    except Exception as e:
        print(f'[sim] load error: {e}')
    return None

def main():
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    parser = argparse.ArgumentParser(description="Scoratron LED Matrix")
    parser.add_argument("--sport", choices=["nfl", "nba", "auto"], default="auto")
    parser.add_argument("--scroll", action="store_true")
    parser.add_argument("--game-index", type=int, default=None)
    parser.add_argument("--scroll-dwell", type=int, default=10)
    parser.add_argument("--refresh", type=int, default=30)
    parser.add_argument("--brightness", type=int, default=60)
    parser.add_argument("--no-logo", action="store_true")
    args = parser.parse_args()

    # Override CLI args with web UI settings if available
    webui = load_webui_settings()
    if webui:
        print('[settings] Loading from web UI settings file')
        if 'sport' in webui:        args.sport        = webui['sport']
        if 'scroll' in webui:       args.scroll       = webui['scroll']
        if 'scroll_dwell' in webui: args.scroll_dwell = webui['scroll_dwell']
        if 'refresh_rate' in webui: args.refresh      = webui['refresh_rate']
        if 'brightness' in webui:   args.brightness   = webui['brightness']

    # Build fetchers — auto mode polls both leagues
    sports = ["nfl", "nba"] if args.sport == "auto" else [args.sport]

    fetchers = {}
    for sport in sports:
        c = Config(
            sport=sport,
            scroll=args.scroll,
            game_index=args.game_index,
            scroll_dwell=args.scroll_dwell,
            refresh_interval=args.refresh,
            brightness=args.brightness,
            show_logos=not args.no_logo,
        )
        fetchers[sport] = ScoreFetcher(c)

    config = Config(
        sport="nba" if "nba" in sports else sports[0],
        scroll=args.scroll,
        game_index=args.game_index,
        scroll_dwell=args.scroll_dwell,
        refresh_interval=args.refresh,
        brightness=args.brightness,
        show_logos=not args.no_logo,
    )

    print(f"Starting Scoratron — sport: {args.sport}")
    print(f"Scroll: {args.scroll} | Refresh: {args.refresh}s | Brightness: {args.brightness}%")

    renderer = ScoreBugRenderer(config)
    current_game_idx = 0
    last_fetch = 0
    last_scroll_time = time.time()
    games = []
    last_scores = {}
    linger_until = {}
    scroll_offset = 0
    scroll_strip  = None
    LINGER_SECONDS = 30 * 60


    applied_brightness = args.brightness

    while True:
        now = time.time()

        # Reload webui settings on each refresh cycle
        webui = load_webui_settings()

        # Apply brightness changes immediately without a restart
        if webui:
            new_brightness = int(webui.get('brightness', applied_brightness))
            if new_brightness != applied_brightness:
                applied_brightness = new_brightness
                if renderer._matrix:
                    renderer._matrix.brightness = new_brightness
                    print(f'[settings] brightness → {new_brightness}%')

        # Check if WiFi setup is active — show setup instructions instead of scores
        if load_wifi_setup_active():
            renderer.draw_wifi_setup()
            time.sleep(1)
            continue

        # Check if logo parade is active — run it inline on our matrix
        if load_parade_active():
            from logo_parade import run_parade_on_matrix
            import json as _json
            try:
                with open('/tmp/scoratron_parade.json') as _f:
                    _sport = _json.load(_f).get('sport', 'nba')
            except Exception:
                _sport = 'nba'
            if renderer._matrix and renderer._offscreen:
                renderer._offscreen = run_parade_on_matrix(
                    renderer._matrix, renderer._offscreen,
                    sport=_sport,
                    stop_fn=lambda: not load_parade_active(),
                )
            else:
                # Preview mode — just wait
                while load_parade_active():
                    time.sleep(0.5)
            continue

        # Refresh scores from API — 5s when live, configured rate otherwise, 5 min when no games
        has_live = any(g.is_live for g in games)
        live_interval = int(webui.get('live_refresh_rate', 5)) if webui else 5
        effective_interval = live_interval if has_live else (config.refresh_interval if games else 300)
        if now - last_fetch >= effective_interval:
            new_games = []
            for sport, fetcher in fetchers.items():
                g = fetcher.fetch_games()
                if g:
                    new_games.extend(g)

            # Assign linger windows to finished games.
            # Games whose start time is > 6 hours ago are stale (off-season relics,
            # yesterday's games, etc.) and are suppressed immediately.
            # Games that started recently get a 30-minute display window.
            for game in new_games:
                if game.status == "post" and game.game_id not in linger_until:
                    if game_started_within(game, 6 * 3600):
                        linger_until[game.game_id] = now + LINGER_SECONDS
                        print(f"[linger] {game.away.abbreviation} vs {game.home.abbreviation} final — showing for 30min")
                    else:
                        linger_until[game.game_id] = 0  # stale — suppress
                        print(f"[linger] {game.away.abbreviation} vs {game.home.abbreviation} stale — suppressed")

            # Drop finished games whose linger window has closed
            new_games = [g for g in new_games
                         if g.status != "post" or now < linger_until.get(g.game_id, 0)]

            # Add lingering finals that dropped off the API before their window closed
            current_ids = {g.game_id for g in new_games}
            for game in games:
                if game.status == "post" and game.game_id not in current_ids:
                    if game.game_id in linger_until and now < linger_until[game.game_id]:
                        new_games.append(game)

            # Prune entries that expired more than 24h ago (keep t=0 "suppressed" entries
            # so stale games are never re-admitted with a fresh timer)
            linger_until = {gid: t for gid, t in linger_until.items()
                            if t == 0 or now - t < 86400}

            # Priority: live → lingering finals → upcoming (once first game within 60 min)
            live     = [g for g in new_games if g.is_live]
            finished = [g for g in new_games if g.status == "post"]
            upcoming = [g for g in new_games if g.status == "pre"]

            if live:
                games = live
            elif finished:
                games = finished
            elif upcoming:
                from datetime import datetime as _dt, timezone as _tz, timedelta as _td
                _now = _dt.now(_tz.utc)
                _cutoff = _now + _td(minutes=60)
                def _start(g):
                    if not g.start_time_utc:
                        return _now
                    try:
                        return _dt.fromisoformat(g.start_time_utc.replace("Z", "+00:00"))
                    except Exception:
                        return _now
                earliest_start = min(_start(g) for g in upcoming)
                if earliest_start <= _cutoff:
                    # Show all games on the same local calendar day as the first game
                    first_day = earliest_start.astimezone().date()
                    games = [g for g in upcoming if _start(g).astimezone().date() == first_day]
                else:
                    games = []
            else:
                games = []

            print(f"Refreshed: {len(games)} displayable games (live={len(live)} finished={len(finished)} upcoming={len(upcoming)})")
            last_fetch = now
            scroll_strip = None   # rebuild on next scroll frame

        # Check for simulator game — takes over the display entirely
        sim = load_sim_game()
        if sim and sim.get('active'):
            from config import TEAM_COLORS
            away_abbr = sim['away_abbr']
            home_abbr = sim['home_abbr']
            sport = sim.get('sport', 'nba')
            sim_game = GameState(
                game_id='sim',
                sport=sport,
                status='in',
                status_detail=sim.get('clock', ''),
                period=sim.get('period', 4),
                clock=sim.get('clock', '0:00'),
                is_live=True,
                is_halftime=sim.get('is_halftime', False),
                is_ot=sim.get('is_ot', False),
                is_playoff=sim.get('is_playoff', False),
                series_summary=sim.get('series_summary', ''),
                game_label=sim.get('game_label', ''),
                possession=sim.get('possession', None),
                down_distance=sim.get('down_distance', None),
                away_win_pct=sim.get('away_win_pct', 0.5),
                home_win_pct=sim.get('home_win_pct', 0.5),
                away=TeamInfo(
                    name=away_abbr,
                    abbreviation=away_abbr,
                    score=sim.get('away_score', 0),
                    timeouts=3, fouls=0,
                    logo_path=f'logos/{sport}/{away_abbr}.png',
                    color=TEAM_COLORS.get(away_abbr, (128, 128, 128)),
                    record=sim.get('away_record', ''),
                    seed=sim.get('away_seed', 0),
                ),
                home=TeamInfo(
                    name=home_abbr,
                    abbreviation=home_abbr,
                    score=sim.get('home_score', 0),
                    timeouts=3, fouls=0,
                    logo_path=f'logos/{sport}/{home_abbr}.png',
                    color=TEAM_COLORS.get(home_abbr, (128, 128, 128)),
                    record=sim.get('home_record', ''),
                    seed=sim.get('home_seed', 0),
                ),
            )
            # Check for a flash request from the web UI
            flash_path = '/tmp/scoratron_flash.json'
            if os.path.exists(flash_path):
                try:
                    with open(flash_path) as f:
                        flash_data = json.load(f)
                    team = flash_data.get('team')
                    if team:
                        with open(flash_path, 'w') as f:
                            json.dump({}, f)  # mark consumed (can't delete, owned by root)
                        renderer.flash_score(sim_game, team)
                except Exception as e:
                    print(f'[flash] error: {e}')

            renderer.draw_game(sim_game)
            write_preview(sim_game)
            time.sleep(0.1)
            continue

        # Force weather display (overrides game display if enabled)
        zip_code     = webui.get('zip_code', '')     if webui else ''
        force_weather = webui.get('force_weather', False) if webui else False
        if force_weather:
            weather = get_weather(zip_code) if zip_code else get_weather_by_ip()
            if weather:
                renderer.draw_weather(weather)
                write_weather_preview(weather)
                time.sleep(1)
                continue

        if not games:
            weather = get_weather(zip_code) if zip_code else get_weather_by_ip()
            if weather:
                renderer.draw_weather(weather)
                write_weather_preview(weather)
                time.sleep(1)
                continue
            renderer.draw_no_games(args.sport if args.sport != "auto" else "NBA/NFL")
            time.sleep(5)
            continue

        # Pick game to show — check for pinned game from web UI first
        pinned_id = webui.get('pinned_game') if webui else None
        if pinned_id:
            pinned_matches = [i for i, g in enumerate(games) if g.game_id == pinned_id]
            idx = pinned_matches[0] if pinned_matches else current_game_idx % len(games)
        elif config.game_index is not None:
            idx = min(config.game_index, len(games) - 1)
        else:
            idx = current_game_idx % len(games)

        game = games[idx]

        # Check for score change and flash
        prev = last_scores.get(game.game_id)
        if prev and game.is_live:
            prev_away, prev_home = prev
            if game.away.score > prev_away:
                renderer.flash_score(game, 'away')
            elif game.home.score > prev_home:
                renderer.flash_score(game, 'home')

        last_scores[game.game_id] = (game.away.score, game.home.score)

        # Continuous scroll mode
        if webui and webui.get('continuous_scroll') and len(games) > 1 and not pinned_id:
            if scroll_strip is None:
                scroll_strip = renderer.render_game_strip(games)
            renderer.push_scroll_frame(scroll_strip, scroll_offset)
            scroll_offset = (scroll_offset + 1) % scroll_strip.width
            write_preview(games[idx])
            time.sleep(0.03)
            continue

        renderer.draw_game(games[idx])
        write_preview(games[idx])

        # Dwell scroll — transition to next game after scroll_dwell seconds
        scroll_on    = webui.get('scroll', args.scroll) if webui else args.scroll
        scroll_dwell = webui.get('scroll_dwell', config.scroll_dwell) if webui else config.scroll_dwell
        if scroll_on and len(games) > 1 and not pinned_id:
            if now - last_scroll_time >= scroll_dwell:
                old_img = renderer.render_game_image(games[idx])
                current_game_idx = (current_game_idx + 1) % len(games)
                new_idx = current_game_idx % len(games)
                new_img = renderer.render_game_image(games[new_idx])
                renderer.animate_scroll_transition(old_img, new_img)
                last_scroll_time = now

        time.sleep(0.1)

if __name__ == "__main__":
    main()