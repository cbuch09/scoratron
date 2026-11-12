#!/usr/bin/env bash
# auto_update.sh — daily auto-update from GitHub (run by scoratron-update.timer).
#
# Pulls origin/master as the repo owner (so the owner's git/SSH config is used),
# fast-forward only, and restarts the services only if the code changed.
# Settings (settings.json) are gitignored, so they are never touched.
#
# Manual run:   sudo bash auto_update.sh
# Logs:         journalctl -u scoratron-update

set -u

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OWNER="$(stat -c %U "$DIR")"
VENV="$DIR/venv"

log() { echo "[auto-update] $*"; }
run_git() { runuser -u "$OWNER" -- git -C "$DIR" "$@"; }

before="$(run_git rev-parse HEAD)" || { log "not a git repo: $DIR"; exit 1; }

if ! out="$(run_git pull --ff-only origin master 2>&1)"; then
    log "pull failed — leaving current version running:"
    echo "$out" | sed 's/^/    /'
    exit 1
fi

after="$(run_git rev-parse HEAD)"
if [ "$before" = "$after" ]; then
    log "already up to date (${after:0:7})"
    exit 0
fi

log "updated ${before:0:7} -> ${after:0:7}:"
run_git log --oneline "$before..$after" | sed 's/^/    /'
changed="$(run_git diff --name-only "$before" "$after")"

if grep -qx 'requirements.txt' <<<"$changed"; then
    log "requirements.txt changed — updating Python packages"
    "$VENV/bin/pip" install -q -r "$DIR/requirements.txt" || log "WARNING: pip install failed"
fi

if grep -qE '^(install\.sh|wifi_setup/)' <<<"$changed"; then
    log "NOTE: installer/system files changed — run 'sudo bash $DIR/install.sh' to apply them"
fi

log "restarting services"
systemctl restart scoratron scoratron-web
log "done"
