"""
settings_store.py - Single source of truth for user settings.

Settings live in <repo>/settings.json, which is gitignored, so each board keeps
its own settings across reboots and `git pull` updates. (They used to live in
/tmp, which is cleared on every boot.)

Used by both main.py (display) and webui/app.py (web UI).
"""
import json
import os

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'settings.json')
_LEGACY_FILE  = '/tmp/scoratron_settings.json'   # pre-persistence location

DEFAULT_SETTINGS = {
    'sport': 'auto',
    'scroll': True,
    'scroll_dwell': 10,
    'refresh_rate': 15,
    'live_refresh_rate': 5,
    'brightness': 60,
    'pinned_game': None,
    'zip_code': '',
    'force_weather': False,
    'continuous_scroll': False,
    # Night schedule — dims the board overnight in case it's left on
    'night_enabled': True,
    'night_start': '23:00',
    'night_end': '08:00',
    'night_brightness': 30,
}


def _migrate_legacy():
    """One-time: if /tmp holds newer settings than the repo file, keep them."""
    try:
        if os.path.exists(_LEGACY_FILE) and (
                not os.path.exists(SETTINGS_FILE)
                or os.path.getmtime(_LEGACY_FILE) > os.path.getmtime(SETTINGS_FILE)):
            with open(_LEGACY_FILE) as f:
                legacy = json.load(f)
            save_settings({**load_settings(), **legacy})
            print(f'[settings] migrated {_LEGACY_FILE} -> {SETTINGS_FILE}')
        if os.path.exists(_LEGACY_FILE):
            os.remove(_LEGACY_FILE)
    except Exception as e:
        print(f'[settings] legacy migration skipped: {e}')


def load_settings():
    """Return settings merged over defaults. Never raises."""
    s = DEFAULT_SETTINGS.copy()
    try:
        with open(SETTINGS_FILE) as f:
            s.update(json.load(f))
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f'[settings] load error: {e}')
    return s


def save_settings(s):
    """Atomically write settings so a reader never sees a half-written file."""
    tmp = SETTINGS_FILE + '.tmp'
    try:
        with open(tmp, 'w') as f:
            json.dump(s, f, indent=2)
        os.chmod(tmp, 0o666)
        os.replace(tmp, SETTINGS_FILE)
    except Exception as e:
        print(f'[settings] save error: {e}')


def init_settings():
    """Ensure the settings file exists and carries every current default key."""
    _migrate_legacy()
    current = load_settings()
    on_disk = {}
    try:
        with open(SETTINGS_FILE) as f:
            on_disk = json.load(f)
    except Exception:
        pass
    if current != on_disk:
        save_settings(current)
