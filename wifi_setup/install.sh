#!/bin/bash
# install.sh — sets up the Scoratron WiFi provisioning system. Idempotent:
# safe to re-run (the main install.sh and auto_update.sh both call it).
#   sudo bash /home/admin/scoratron/wifi_setup/install.sh

set -e
DIR=/home/admin/scoratron/wifi_setup

echo "=== Scoratron WiFi Setup Installer ==="

# 1. Packages — NM's hotspot mode needs the dnsmasq binary (dnsmasq-base)
echo "[1/5] Checking packages..."
if ! dpkg -s dnsmasq-base >/dev/null 2>&1; then
    apt-get update -qq
    apt-get install -y dnsmasq-base
fi

# The stock dnsmasq *service* (if installed) holds port 53 on every interface
# and blocks the hotspot's DNS. The board doesn't use it.
if systemctl list-unit-files dnsmasq.service >/dev/null 2>&1; then
    systemctl disable --now dnsmasq.service 2>/dev/null || true
fi
# Old hostapd-based setup is no longer used
systemctl disable --now hostapd.service 2>/dev/null || true

# 2. Permissions
echo "[2/5] Setting permissions..."
chmod 755 "$DIR"/check_wifi.sh "$DIR"/ap_start.sh "$DIR"/ap_stop.sh "$DIR"/do_connect.sh

# 3. Catch-all DNS for the hotspot so phones open the setup page automatically
echo "[3/5] Configuring captive-portal DNS..."
mkdir -p /etc/NetworkManager/dnsmasq-shared.d
printf 'address=/#/192.168.4.1\ndhcp-option=114,http://192.168.4.1/\n' \
    > /etc/NetworkManager/dnsmasq-shared.d/scoratron-captive.conf

# 4. systemd units
echo "[4/5] Installing systemd units..."
install -m 644 "$DIR/scoratron-wifi-setup.service"   /etc/systemd/system/
install -m 644 "$DIR/scoratron-ap.service"           /etc/systemd/system/
install -m 644 "$DIR/scoratron-wifi-connect.service" /etc/systemd/system/

for svc in scoratron scoratron-web; do
    mkdir -p /etc/systemd/system/$svc.service.d
    cat > /etc/systemd/system/$svc.service.d/wifi-setup.conf << 'CONF'
[Unit]
After=scoratron-wifi-setup.service
Wants=scoratron-wifi-setup.service
CONF
done

# 5. Enable
echo "[5/5] Enabling..."
systemctl daemon-reload
systemctl enable scoratron-wifi-setup.service

echo ""
echo "Done. If no known WiFi is reachable at boot, the board broadcasts"
echo "'Scoratron-Setup'. Test any time with:  sudo systemctl start scoratron-ap"
echo "(join 'Scoratron-Setup' from a phone; stop with: sudo systemctl stop scoratron-ap)"
