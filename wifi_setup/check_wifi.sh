#!/bin/bash
# check_wifi.sh — run on boot via scoratron-wifi-setup.service.
# Waits up to 20s for a network connection; if none, starts the setup hotspot
# (scoratron-ap.service) and exits so the display can start.

WIFI_SETUP_FILE="/tmp/scoratron_wifi_setup.json"

echo '{"active": false}' > "$WIFI_SETUP_FILE"
chmod 666 "$WIFI_SETUP_FILE"

echo "[wifi-check] Waiting for network (up to 20s)..."
for i in $(seq 1 20); do
    if nmcli -t -f DEVICE,STATE device 2>/dev/null | grep -v "^lo:" | grep -qE ":(connected|connecting)"; then
        echo "[wifi-check] Connected after ${i}s — normal startup"
        exit 0
    fi
    sleep 1
done

echo "[wifi-check] No network found — starting WiFi setup hotspot"
echo '{"active": true}' > "$WIFI_SETUP_FILE"     # display shows the setup screen
systemctl start --no-block scoratron-ap
exit 0
