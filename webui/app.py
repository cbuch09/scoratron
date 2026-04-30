#!/usr/bin/env python3
"""
Scoratron Web UI - Flask backend
Runs on port 5000, provides REST API and serves the dashboard.
"""

import os
import sys
import json
import time
import glob as glob_mod
import threading
import subprocess
from datetime import datetime
from flask import Flask, jsonify, request, send_from_directory
import requests as req
try:
    from PIL import Image
except ImportError:
    Image = None

sys.path.insert(0, '/home/admin/scoratron')
os.chdir('/home/admin/scoratron')

from config import Config, ESPN_ENDPOINTS, TEAM_COLORS
from score_fetcher import ScoreFetcher
from models import GameState, TeamInfo

app = Flask(__name__, static_folder='static')

CERT = '/etc/ssl/certs/ca-certificates.crt'
SETTINGS_FILE = '/tmp/scoratron_settings.json'
SIM_FILE = '/tmp/scoratron_sim.json'
PARADE_FILE = '/tmp/scoratron_parade.json'

DEFAULT_SETTINGS = {
    'sport': 'auto',
    'scroll': True,
    'scroll_dwell': 10,
    'refresh_rate': 15,
    'brightness': 60,
    'pinned_game': None,
    'zip_code': '',
    'force_weather': False,
    'continuous_scroll': False,
}

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE) as f:
            s = DEFAULT_SETTINGS.copy()
            s.update(json.load(f))
            return s
    return DEFAULT_SETTINGS.copy()

def save_settings(s):
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(s, f, indent=2)

# ── Cache ──────────────────────────────────────────────────────────────────
cache = {
    'games': [],
    'raw_nba': {},
    'raw_nfl': {},
    'last_fetch': 0,
}

def fetch_all():
    for sport, url in ESPN_ENDPOINTS.items():
        try:
            r = req.get(url, timeout=10, verify=CERT)
            r.raise_for_status()
            cache[f'raw_{sport}'] = r.json()
        except Exception as e:
            print(f'[web] fetch {sport} error: {e}')

    # Parse games
    settings = load_settings()
    sports = ['nfl','nba'] if settings['sport'] == 'auto' else [settings['sport']]
    all_games = []
    for sport in sports:
        c = Config(sport=sport, refresh_interval=settings['refresh_rate'],
                   brightness=settings['brightness'])
        f = ScoreFetcher(c)
        g = f.fetch_games()
        if g:
            all_games.extend(g)
    cache['games'] = all_games
    cache['last_fetch'] = time.time()

def game_to_dict(g):
    return {
        'game_id': g.game_id,
        'sport': g.sport,
        'status': g.status,
        'status_detail': g.status_detail,
        'period': g.period,
        'clock': g.clock,
        'is_live': g.is_live,
        'is_halftime': g.is_halftime,
        'is_ot': g.is_ot,
        'is_playoff': g.is_playoff,
        'series_summary': g.series_summary,
        'game_label': g.game_label,
        'possession': g.possession,
        'down_distance': g.down_distance,
        'away_win_pct': g.away_win_pct,
        'home_win_pct': g.home_win_pct,
        'away': {
            'name': g.away.name,
            'abbreviation': g.away.abbreviation,
            'score': g.away.score,
            'timeouts': g.away.timeouts,
            'fouls': g.away.fouls,
            'color': g.away.color,
            'record': g.away.record,
            'seed': g.away.seed,
        },
        'home': {
            'name': g.home.name,
            'abbreviation': g.home.abbreviation,
            'score': g.home.score,
            'timeouts': g.home.timeouts,
            'fouls': g.home.fouls,
            'color': g.home.color,
            'record': g.home.record,
            'seed': g.home.seed,
        },
    }

# ── Routes ────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/api/games')
def api_games():
    if time.time() - cache['last_fetch'] > 30:
        fetch_all()
    return jsonify([game_to_dict(g) for g in cache['games']])

@app.route('/api/settings', methods=['GET'])
def api_get_settings():
    return jsonify(load_settings())

def _set_timezone_for_zip(zip_code):
    """Look up the IANA timezone for a zip/city and apply it to the system."""
    try:
        geo = req.get(
            'https://geocoding-api.open-meteo.com/v1/search',
            params={'name': zip_code, 'count': 1, 'format': 'json'},
            timeout=10, verify=CERT,
        )
        geo.raise_for_status()
        results = geo.json().get('results')
        if not results:
            return
        tz = results[0].get('timezone', '')
        if tz:
            subprocess.run(['sudo', 'timedatectl', 'set-timezone', tz], check=True)
            print(f'[settings] timezone set to {tz} for zip {zip_code!r}')
    except Exception as e:
        print(f'[settings] timezone update failed: {e}')

@app.route('/api/settings', methods=['POST'])
def api_post_settings():
    s = load_settings()
    old_zip = s.get('zip_code', '')
    s.update(request.json)
    save_settings(s)
    new_zip = s.get('zip_code', '')
    if new_zip != old_zip:
        if new_zip:
            _set_timezone_for_zip(new_zip)
        subprocess.Popen(['sudo', 'systemctl', 'restart', 'scoratron'])
    return jsonify({'ok': True})

@app.route('/api/refresh', methods=['POST'])
def api_refresh():
    fetch_all()
    return jsonify({'ok': True, 'games': len(cache['games'])})

@app.route('/api/restart', methods=['POST'])
def api_restart():
    subprocess.Popen(['sudo','systemctl','restart','scoratron'])
    return jsonify({'ok': True})

@app.route('/api/rawdata')
def api_rawdata():
    fetch_all()
    return jsonify({
        'nba': cache['raw_nba'],
        'nfl': cache['raw_nfl'],
    })

@app.route('/api/sysinfo')
def api_sysinfo():
    def read(cmd):
        try:
            return subprocess.check_output(cmd, shell=True).decode().strip()
        except:
            return 'N/A'

    temp    = read("vcgencmd measure_temp 2>/dev/null | cut -d= -f2")
    uptime  = read("uptime -p")
    ip      = read("hostname -I | awk '{print $1}'")
    mem     = read("free -h | awk '/^Mem:/{print $3\"/\"$2}'")
    service = read("systemctl is-active scoratron")
    hostname = read("hostname")
    os_name  = read("grep PRETTY_NAME /etc/os-release 2>/dev/null | cut -d'\"' -f2")
    kernel   = read("uname -r")
    arch     = read("uname -m")
    updates  = read("apt-get -s upgrade 2>/dev/null | grep -c '^Inst' || echo 0")

    # Extract just the idle % and calculate usage
    cpu_line = read("top -bn1 | grep 'Cpu(s)'")
    try:
        idle = float(cpu_line.split('id')[0].strip().split()[-1].replace(',', '.'))
        cpu = f"{round(100 - idle)}%"
    except:
        cpu = 'N/A'

    return jsonify({
        'temp': temp,
        'uptime': uptime,
        'ip': ip,
        'cpu': cpu,
        'memory': mem,
        'service': service,
        'hostname': hostname,
        'os_name': os_name,
        'kernel': kernel,
        'arch': arch,
        'updates_available': updates,
    })

@app.route('/api/system/update', methods=['POST'])
def api_system_update():
    """Run apt-get update && apt-get upgrade -y in the background."""
    try:
        subprocess.Popen(
            ['sudo', 'apt-get', 'update', '-qq'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        return jsonify({'ok': True, 'msg': 'Update started — check system logs for progress'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/system/upgrade', methods=['POST'])
def api_system_upgrade():
    """Run apt-get upgrade -y in the background."""
    try:
        subprocess.Popen(
            ['sudo', 'apt-get', 'upgrade', '-y', '-qq'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        return jsonify({'ok': True, 'msg': 'Upgrade started — this may take several minutes'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

def _git(args, timeout=30):
    """Run a git command as the 'admin' user (repo owner with SSH keys)."""
    return subprocess.run(
        ['sudo', '-u', 'admin', 'git', '-C', '/home/admin/scoratron'] + args,
        capture_output=True, text=True, timeout=timeout
    )

@app.route('/api/system/git-push', methods=['POST'])
def api_git_push():
    """Stage all changes, commit, and push to origin."""
    try:
        msg = (request.json or {}).get('message', 'Update from Scoratron web UI')
        _git(['add', '-u'])
        diff = _git(['diff', '--cached', '--quiet'])
        if diff.returncode != 0:
            r = _git(['commit', '-m', msg])
            if r.returncode != 0:
                return jsonify({'ok': False, 'error': r.stderr.strip() or r.stdout.strip()})
        result = _git(['push', 'origin', 'master'])
        if result.returncode == 0:
            return jsonify({'ok': True, 'msg': 'Pushed to GitHub successfully'})
        else:
            return jsonify({'ok': False, 'error': result.stderr.strip() or result.stdout.strip()})
    except subprocess.TimeoutExpired:
        return jsonify({'ok': False, 'error': 'Push timed out (30s)'}), 500
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/system/git-pull', methods=['POST'])
def api_git_pull():
    """Pull latest code from origin and restart services."""
    try:
        result = _git(['pull', 'origin', 'master'])
        if result.returncode != 0:
            return jsonify({'ok': False, 'error': result.stderr.strip() or result.stdout.strip()})
        output = result.stdout.strip()
        subprocess.Popen(['sudo', 'systemctl', 'restart', 'scoratron', 'scoratron-web'])
        return jsonify({'ok': True, 'msg': output or 'Already up to date. Services restarting...'})
    except subprocess.TimeoutExpired:
        return jsonify({'ok': False, 'error': 'Pull timed out (30s)'}), 500
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/simulate', methods=['POST'])
def api_simulate():
    data = request.json
    sport = data.get('sport', 'nba')
    away_abbr = data.get('away_abbr', 'BOS')
    home_abbr = data.get('home_abbr', 'MIA')
    away_score = data.get('away_score', 98)
    home_score = data.get('home_score', 94)
    period = data.get('period', 4)
    clock = data.get('clock', '2:15')
    is_halftime = data.get('is_halftime', False)
    is_ot = data.get('is_ot', False)
    away_win_pct = data.get('away_win_pct', 0.6)

    sim = {
        'active': True,
        'sport': sport,
        'away_abbr': away_abbr,
        'home_abbr': home_abbr,
        'away_score': away_score,
        'home_score': home_score,
        'away_record': data.get('away_record', ''),
        'home_record': data.get('home_record', ''),
        'away_seed': int(data.get('away_seed', 0) or 0),
        'home_seed': int(data.get('home_seed', 0) or 0),
        'period': period,
        'clock': clock,
        'is_halftime': is_halftime,
        'is_ot': is_ot,
        'is_playoff': data.get('is_playoff', False),
        'series_summary': data.get('series_summary', ''),
        'game_label': data.get('game_label', ''),
        'away_win_pct': away_win_pct,
        'home_win_pct': 1 - away_win_pct,
    }
    with open('/tmp/scoratron_sim.json', 'w') as f:
        json.dump(sim, f)
    return jsonify({'ok': True})

@app.route('/api/simulate/flash', methods=['POST'])
def api_simulate_flash():
    data = request.json or {}
    team = data.get('team', 'away')  # 'away' or 'home'
    path = '/tmp/scoratron_flash.json'
    with open(path, 'w') as f:
        json.dump({'team': team}, f)
    os.chmod(path, 0o666)  # allow daemon (main.py) to overwrite to mark consumed
    return jsonify({'ok': True})

@app.route('/api/simulate/clear', methods=['POST'])
def api_simulate_clear():
    sim_path = '/tmp/scoratron_sim.json'
    if os.path.exists(sim_path):
        os.remove(sim_path)
    return jsonify({'ok': True})

@app.route('/api/current')
def api_current():
    path = '/tmp/scoratron_current.json'
    if os.path.exists(path):
        with open(path) as f:
            return jsonify(json.load(f))
    return jsonify(None)

@app.route('/api/wifi/status')
def api_wifi_status():
    def nm(args):
        try:
            return subprocess.check_output(['nmcli'] + args,
                                           stderr=subprocess.DEVNULL).decode().strip()
        except Exception:
            return ''
    # Current WiFi connection
    raw = nm(['-t', '-f', 'NAME,TYPE,DEVICE,STATE', 'connection', 'show', '--active'])
    wifi_name = ''
    for line in raw.splitlines():
        parts = line.split(':')
        if len(parts) >= 4 and '802-11-wireless' in parts[1] and parts[3] == 'activated':
            wifi_name = parts[0]
            break
    # IP address on wlan0
    ip = ''
    try:
        ip_raw = subprocess.check_output(
            ['ip', '-4', 'addr', 'show', 'wlan0'], stderr=subprocess.DEVNULL
        ).decode()
        for line in ip_raw.splitlines():
            line = line.strip()
            if line.startswith('inet '):
                ip = line.split()[1].split('/')[0]
                break
    except Exception:
        pass
    return jsonify({'connected': bool(wifi_name), 'ssid': wifi_name, 'ip': ip})

@app.route('/api/wifi/networks')
def api_wifi_networks():
    try:
        raw = subprocess.check_output(
            ['nmcli', '-t', '-f', 'SSID,SIGNAL,SECURITY', 'device', 'wifi', 'list',
             'ifname', 'wlan0'],
            stderr=subprocess.DEVNULL
        ).decode().strip()
        seen = set()
        networks = []
        for line in raw.splitlines():
            parts = line.split(':')
            if not parts or not parts[0]:
                continue
            ssid = parts[0]
            if ssid in seen:
                continue
            seen.add(ssid)
            signal   = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
            security = parts[2] if len(parts) > 2 else ''
            networks.append({'ssid': ssid, 'signal': signal,
                             'secured': bool(security and security != '--')})
        networks.sort(key=lambda n: -n['signal'])
        return jsonify(networks)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/wifi/connect', methods=['POST'])
def api_wifi_connect():
    data     = request.json or {}
    ssid     = data.get('ssid', '').strip()
    password = data.get('password', '').strip()
    if not ssid or len(ssid) > 64 or len(password) > 63:
        return jsonify({'ok': False, 'error': 'Invalid SSID or password'}), 400
    try:
        cmd = ['nmcli', 'device', 'wifi', 'connect', ssid, 'ifname', 'wlan0']
        if password:
            cmd += ['password', password]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        ok = result.returncode == 0
        return jsonify({'ok': ok, 'msg': (result.stdout or result.stderr).strip()})
    except subprocess.TimeoutExpired:
        return jsonify({'ok': False, 'error': 'Connection timed out'}), 504
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/wifi/forget', methods=['POST'])
def api_wifi_forget():
    data = request.json or {}
    ssid = data.get('ssid', '').strip()
    if not ssid:
        return jsonify({'ok': False, 'error': 'No SSID provided'}), 400
    try:
        result = subprocess.run(
            ['nmcli', 'connection', 'delete', ssid],
            capture_output=True, text=True, timeout=10
        )
        return jsonify({'ok': result.returncode == 0,
                        'msg': (result.stdout or result.stderr).strip()})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

WMO_CODES = {
    0:'Clear', 1:'Mostly Clear', 2:'Partly Cloudy', 3:'Overcast',
    45:'Fog', 48:'Icy Fog',
    51:'Light Drizzle', 53:'Drizzle', 55:'Heavy Drizzle',
    61:'Light Rain', 63:'Rain', 65:'Heavy Rain',
    71:'Light Snow', 73:'Snow', 75:'Heavy Snow', 77:'Snow Grains',
    80:'Light Showers', 81:'Showers', 82:'Heavy Showers',
    85:'Snow Showers', 86:'Heavy Snow Showers',
    95:'Thunderstorm', 96:'Thunderstorm+Hail', 99:'Thunderstorm+Hail',
}

def _wind_dir(deg):
    dirs = ['N','NE','E','SE','S','SW','W','NW']
    return dirs[round(deg / 45) % 8]

def _fetch_weather(zip_code):
    """Geocode zip via Open-Meteo, then fetch current conditions. Returns dict or raises."""
    geo = req.get(
        'https://geocoding-api.open-meteo.com/v1/search',
        params={'name': zip_code, 'count': 1, 'format': 'json'},
        timeout=10, verify=CERT,
    )
    geo.raise_for_status()
    results = geo.json().get('results')
    if not results:
        raise ValueError(f'Zip code {zip_code!r} not found')
    lat = results[0]['latitude']
    lon = results[0]['longitude']
    city = results[0].get('name', zip_code)

    wx = req.get(
        'https://api.open-meteo.com/v1/forecast',
        params={
            'latitude': lat, 'longitude': lon,
            'current': ('temperature_2m,apparent_temperature,relative_humidity_2m,'
                        'weather_code,wind_speed_10m,wind_direction_10m,uv_index,is_day'),
            'temperature_unit': 'fahrenheit',
            'wind_speed_unit': 'mph',
            'forecast_days': 1,
        },
        timeout=10, verify=CERT,
    )
    wx.raise_for_status()
    cur = wx.json()['current']
    code = int(cur.get('weather_code', 0))
    return {
        'temp_f':       str(round(cur['temperature_2m'])),
        'feels_like_f': str(round(cur['apparent_temperature'])),
        'condition':    WMO_CODES.get(code, f'Code {code}'),
        'humidity':     str(round(cur['relative_humidity_2m'])),
        'wind_mph':     str(round(cur['wind_speed_10m'])),
        'wind_dir':     _wind_dir(cur.get('wind_direction_10m', 0)),
        'uv_index':     str(round(cur.get('uv_index', 0))),
        'is_day':       int(cur.get('is_day', 1)),
        'weather_code': code,
        'zip_code':     zip_code,
        'city':         city,
    }

@app.route('/api/weather')
def api_weather():
    settings = load_settings()
    zip_code = settings.get('zip_code', '').strip()
    if not zip_code:
        return jsonify({'error': 'No zip code configured'}), 400
    try:
        return jsonify(_fetch_weather(zip_code))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/parade/start', methods=['POST'])
def api_parade_start():
    data = request.json or {}
    sport = data.get('sport', 'nba')
    if sport not in ('nfl', 'nba', 'both'):
        sport = 'nba'
    with open(PARADE_FILE, 'w') as f:
        json.dump({'active': True, 'sport': sport}, f)
    os.chmod(PARADE_FILE, 0o666)
    return jsonify({'ok': True})

@app.route('/api/parade/stop', methods=['POST'])
def api_parade_stop():
    with open(PARADE_FILE, 'w') as f:
        json.dump({'active': False}, f)
    os.chmod(PARADE_FILE, 0o666)
    return jsonify({'ok': True})

@app.route('/api/parade/status')
def api_parade_status():
    try:
        with open(PARADE_FILE) as f:
            active = json.load(f).get('active', False)
    except Exception:
        active = False
    return jsonify({'running': active})

# ── Code Editor ──────────────────────────────────────────────────────────────

SCORATRON_DIR = os.path.realpath('/home/admin/scoratron')
EDITABLE_EXT  = {'.py', '.html', '.css', '.js', '.json', '.sh', '.conf',
                 '.md', '.txt', '.service', '.bdf', '.pil'}
SKIP_DIRS     = {'__pycache__', '.git', 'logos', 'logos_web', 'venv', '.venv', 'env'}

def _safe_path(rel):
    """Resolve a relative path, ensuring it stays inside SCORATRON_DIR."""
    full = os.path.realpath(os.path.join(SCORATRON_DIR, rel.lstrip('/')))
    return full if full.startswith(SCORATRON_DIR) else None

def _build_tree(root):
    items = []
    try:
        entries = sorted(os.scandir(root), key=lambda e: (not e.is_dir(), e.name.lower()))
        for e in entries:
            if e.name.startswith('.') or e.name in SKIP_DIRS:
                continue
            rel = os.path.relpath(e.path, SCORATRON_DIR)
            if e.is_dir():
                children = _build_tree(e.path)
                if children:
                    items.append({'name': e.name, 'path': rel, 'type': 'dir', 'children': children})
            elif e.is_file():
                ext = os.path.splitext(e.name)[1].lower()
                if ext in EDITABLE_EXT or e.name in ('Makefile', 'requirements.txt'):
                    items.append({'name': e.name, 'path': rel, 'type': 'file'})
    except PermissionError:
        pass
    return items

@app.route('/api/code/files')
def api_code_files():
    return jsonify(_build_tree(SCORATRON_DIR))

@app.route('/api/code/read')
def api_code_read():
    full = _safe_path(request.args.get('path', ''))
    if not full or not os.path.isfile(full):
        return jsonify({'error': 'Not found'}), 404
    if os.path.splitext(full)[1].lower() not in EDITABLE_EXT:
        return jsonify({'error': 'Unsupported type'}), 403
    try:
        with open(full, encoding='utf-8', errors='replace') as f:
            return jsonify({'content': f.read()})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/code/write', methods=['POST'])
def api_code_write():
    data    = request.json or {}
    full    = _safe_path(data.get('path', ''))
    content = data.get('content', '')
    if not full or not os.path.isfile(full):
        return jsonify({'ok': False, 'error': 'Not found'}), 404
    if os.path.splitext(full)[1].lower() not in EDITABLE_EXT:
        return jsonify({'ok': False, 'error': 'Unsupported type'}), 403
    try:
        with open(full, 'w', encoding='utf-8') as f:
            f.write(content)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/logos/<sport>/<filename>')
def serve_logo(sport, filename):
    # Try web resolution first (64x64), fall back to matrix size (20x20)
    web_path = f'/home/admin/scoratron/logos/{sport}_web'
    matrix_path = f'/home/admin/scoratron/logos/{sport}'
    if os.path.exists(os.path.join(web_path, filename)):
        return send_from_directory(web_path, filename)
    return send_from_directory(matrix_path, filename)

# ── Logo Editor ───────────────────────────────────────────────────────────────

LOGO_BASE = '/home/admin/scoratron/logos'

def _logo_path(sport, abbr):
    return os.path.join(LOGO_BASE, sport, f'{abbr}.png')

def _safe_logo(sport, abbr):
    """Return resolved path only if it stays inside LOGO_BASE."""
    p = os.path.realpath(_logo_path(sport, abbr))
    return p if p.startswith(os.path.realpath(LOGO_BASE)) else None

def _ensure_all_originals():
    """At startup, copy every team logo to .original.png if not already present.
    This guarantees Reset to Default always works, even before any edits."""
    import shutil
    for sport in ('nba', 'nfl'):
        sport_dir = os.path.join(LOGO_BASE, sport)
        if not os.path.isdir(sport_dir):
            continue
        for f in sorted(os.listdir(sport_dir)):
            if not f.endswith('.png'):
                continue
            base = f[:-4]
            if '.' in base:  # skip .original, .prev, .current, etc.
                continue
            logo_path = os.path.join(sport_dir, f)
            original_path = os.path.join(sport_dir, f'{base}.original.png')
            if not os.path.exists(original_path):
                shutil.copy2(logo_path, original_path)

@app.route('/api/logo-editor/list')
def logo_editor_list():
    include_originals = request.args.get('include_originals', 'false').lower() == 'true'
    result = {}
    for sport in ('nba', 'nfl'):
        sport_dir = os.path.join(LOGO_BASE, sport)
        if not os.path.isdir(sport_dir):
            result[sport] = []
            continue
        logos = []
        originals = []
        for f in sorted(os.listdir(sport_dir)):
            if not f.endswith('.png'):
                continue
            base = f[:-4]
            if '.' in base:
                if include_originals and f.endswith('.original.png'):
                    abbr = base[:base.rfind('.original')]
                    originals.append({'abbr': abbr, 'sport': sport, 'is_original': True})
                continue
            logos.append({'abbr': base, 'sport': sport, 'is_original': False})
        result[sport] = logos + (originals if include_originals else [])
    return jsonify(result)

@app.route('/api/logo-editor/pixels/<sport>/<abbr>')
def logo_editor_pixels(sport, abbr):
    if not Image:
        return jsonify({'error': 'Pillow not installed'}), 500
    path = _safe_logo(sport, abbr)
    if not path:
        return jsonify({'error': 'Invalid path'}), 404
    variant = request.args.get('variant', '')
    if variant == 'original':
        path = path.replace('.png', '.original.png')
    if not os.path.exists(path):
        return jsonify({'error': 'Logo not found'}), 404
    img = Image.open(path).convert('RGBA')
    w, h = img.size
    pixels = []
    for y in range(h):
        row = []
        for x in range(w):
            r, g, b, a = img.getpixel((x, y))
            row.append([r, g, b, a])
        pixels.append(row)
    return jsonify({'width': w, 'height': h, 'pixels': pixels})

@app.route('/api/logo-editor/save/<sport>/<abbr>', methods=['POST'])
def logo_editor_save(sport, abbr):
    if not Image:
        return jsonify({'ok': False, 'error': 'Pillow not installed'}), 500
    path = _safe_logo(sport, abbr)
    if not path:
        return jsonify({'ok': False, 'error': 'Invalid path'}), 400
    data = request.json or {}
    pixels = data.get('pixels')
    if not pixels:
        return jsonify({'ok': False, 'error': 'No pixel data'}), 400
    h = len(pixels)
    w = len(pixels[0]) if h else 0
    if w == 0:
        return jsonify({'ok': False, 'error': 'Empty pixel data'}), 400

    import shutil
    # First-ever save: capture the shipped logo as .original.png so Reset to Default always works
    original_path = path.replace('.png', '.original.png')
    if os.path.exists(path) and not os.path.exists(original_path):
        shutil.copy2(path, original_path)

    img = Image.new('RGBA', (w, h))
    flat = [(int(px[0]), int(px[1]), int(px[2]), int(px[3])) for row in pixels for px in row]
    img.putdata(flat)
    img.save(path)
    return jsonify({'ok': True})

@app.route('/api/logo-editor/set-current/<sport>/<abbr>', methods=['POST'])
def logo_editor_set_current(sport, abbr):
    """Save the current editor pixels as a named checkpoint (.current.png)."""
    if not Image:
        return jsonify({'ok': False, 'error': 'Pillow not installed'}), 500
    path = _safe_logo(sport, abbr)
    if not path:
        return jsonify({'ok': False, 'error': 'Invalid path'}), 400
    data = request.json or {}
    pixels = data.get('pixels')
    if not pixels:
        return jsonify({'ok': False, 'error': 'No pixel data'}), 400
    h = len(pixels); w = len(pixels[0]) if h else 0
    if not w:
        return jsonify({'ok': False, 'error': 'Empty pixel data'}), 400
    current_path = path.replace('.png', '.current.png')
    img = Image.new('RGBA', (w, h))
    flat = [(int(px[0]), int(px[1]), int(px[2]), int(px[3])) for row in pixels for px in row]
    img.putdata(flat)
    img.save(current_path)
    return jsonify({'ok': True})

@app.route('/api/logo-editor/reset-default/<sport>/<abbr>', methods=['POST'])
def logo_editor_reset_default(sport, abbr):
    """Return pixel data from .original.png (the shipped state).
    Falls back to current on-disk file if the logo has never been saved via the editor."""
    if not Image:
        return jsonify({'ok': False, 'error': 'Pillow not installed'}), 500
    path = _safe_logo(sport, abbr)
    if not path:
        return jsonify({'ok': False, 'error': 'Invalid path'}), 400
    original_path = path.replace('.png', '.original.png')
    # Use .original.png if it exists; otherwise the on-disk file IS the original
    source = original_path if os.path.exists(original_path) else path
    if not os.path.exists(source):
        return jsonify({'ok': False, 'error': 'Logo not found'}), 404
    img = Image.open(source).convert('RGBA')
    ww, hh = img.size
    pixels = [[[*img.getpixel((x, y))] for x in range(ww)] for y in range(hh)]
    return jsonify({'ok': True, 'pixels': pixels})

@app.route('/api/logo-editor/delete/<sport>/<abbr>', methods=['POST'])
def logo_editor_delete(sport, abbr):
    path = _safe_logo(sport, abbr)
    if not path or not os.path.exists(path):
        return jsonify({'ok': False, 'error': 'Logo not found'}), 404
    os.remove(path)
    for suffix in ('.prev.png', '.original.png', '.current.png'):
        aux = path.replace('.png', suffix)
        if os.path.exists(aux):
            os.remove(aux)
    for f in glob_mod.glob(path.replace('.png', '.backup.*.png')):
        os.remove(f)
    return jsonify({'ok': True})

if __name__ == '__main__':
    _ensure_all_originals()
    fetch_all()
    app.run(host='0.0.0.0', port=80, debug=False)
