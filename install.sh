#!/usr/bin/env bash
# Scoratron installer — run as root or with sudo on a Raspberry Pi
# Usage: sudo bash install.sh [--no-logos]
set -e

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$INSTALL_DIR/venv"
RGB_SRC="/tmp/rpi-rgb-led-matrix"
SERVICE_USER="${SUDO_USER:-admin}"

echo "==> Scoratron installer"
echo "    Install dir : $INSTALL_DIR"
echo "    Venv        : $VENV_DIR"
echo "    Service user: $SERVICE_USER"
echo ""

# ── 1. System packages ────────────────────────────────────────────────────────
echo "==> Installing system packages..."
apt-get update -qq
apt-get install -y \
    python3 python3-dev python3-venv \
    git gcc g++ make \
    libssl-dev ca-certificates \
    --no-install-recommends

# ── 2. Python venv + pip deps ─────────────────────────────────────────────────
echo "==> Creating Python venv at $VENV_DIR..."
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -r "$INSTALL_DIR/requirements.txt" -q
echo "    Python deps installed."

# ── 3. rpi-rgb-led-matrix C library + Python bindings ────────────────────────
echo "==> Building rpi-rgb-led-matrix..."
if [ -d "$RGB_SRC" ]; then
    echo "    Source already present, skipping clone."
else
    echo "    Cloning rpi-rgb-led-matrix..."
    git clone --depth=1 https://github.com/hzeller/rpi-rgb-led-matrix.git "$RGB_SRC"
    echo "    Clone done."
fi

# Imaging.h ships only in Pillow's source tree, not in binary wheels.
# Fetch just that one file from GitHub rather than downloading the full sdist.
if true; then
    PILLOW_VER="$("$VENV_DIR/bin/pip" show Pillow | awk '/^Version:/{print $2}')"
    echo "    Fetching Pillow $PILLOW_VER libImaging headers..."
    "$VENV_DIR/bin/python3" -c "
import urllib.request, json, os

ver = '$PILLOW_VER'
dest_dir = '$RGB_SRC/bindings/python/rgbmatrix/shims/'
api = 'https://api.github.com/repos/python-pillow/Pillow/contents/src/libImaging?ref=' + ver

with urllib.request.urlopen(api) as r:
    entries = json.load(r)

for entry in entries:
    if entry['name'].endswith('.h'):
        urllib.request.urlretrieve(entry['download_url'], os.path.join(dest_dir, entry['name']))
        print('    Fetched', entry['name'])
"
fi

echo "    Compiling rgbmatrix C extensions (may take several minutes on a Pi)..."
CMAKE_BUILD_PARALLEL_LEVEL=1 "$VENV_DIR/bin/pip" install -e "$RGB_SRC"
echo "    rgbmatrix built and installed."

# ── 4. Font files ─────────────────────────────────────────────────────────────
echo "==> Installing fonts..."
mkdir -p "$INSTALL_DIR/fonts"
FONT_BASE="https://github.com/dhepper/font8x8/raw/master"
# tom-thumb and 5x7 ship with the repo — nothing to download if already present
if [ ! -f "$INSTALL_DIR/fonts/tom-thumb.pil" ]; then
    echo "    WARNING: fonts/tom-thumb.pil not found — copy font files manually."
fi

# ── 5. Logo directories ───────────────────────────────────────────────────────
echo "==> Creating logo directories..."
mkdir -p "$INSTALL_DIR/logos/nba_web"
mkdir -p "$INSTALL_DIR/logos/nfl_web"
# logos/nba and logos/nfl are included in the repo — no download needed

# ── 7. systemd service files ──────────────────────────────────────────────────
echo "==> Installing systemd services..."

cat > /etc/systemd/system/scoratron.service <<EOF
[Unit]
Description=Scoratron LED Matrix Display
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
ExecStart=$VENV_DIR/bin/python3 $INSTALL_DIR/main.py --scroll
Environment=SSL_CERT_FILE=$VENV_DIR/lib/python$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')/site-packages/certifi/cacert.pem
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/scoratron-web.service <<EOF
[Unit]
Description=Scoratron Web UI
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR/webui
ExecStart=$VENV_DIR/bin/python3 $INSTALL_DIR/webui/app.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable scoratron scoratron-web
systemctl restart scoratron scoratron-web

echo ""
echo "==> Scoratron installed successfully!"
echo "    Web UI : http://$(hostname -I | awk '{print $1}')"
echo "    Logs   : journalctl -u scoratron -f"
echo ""