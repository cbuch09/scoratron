#!/bin/bash
# check_wifi.sh — run on boot via systemd.
# Waits up to 20s for a network connection.
# If none found, scans for nearby SSIDs then starts the AP + captive portal.

WIFI_SETUP_FILE="/tmp/scoratron_wifi_setup.json"

# Start with setup inactive
echo '{"active": false}' > "$WIFI_SETUP_FILE"
chmod 666 "$WIFI_SETUP_FILE"

echo "[wifi-check] Waiting for network (up to 20s)..."
for i in $(seq 1 20); do
    if nmcli -t -f DEVICE,STATE device 2>/dev/null | grep -q ":connected"; then
        echo "[wifi-check] Connected after ${i}s — normal startup"
        exit 0
    fi
    sleep 1
done

echo "[wifi-check] No network found — starting WiFi setup AP"

# Scan for nearby SSIDs while wlan0 is still in station mode
echo "[wifi-check] Scanning for networks..."
nmcli -t -f SSID device wifi list ifname wlan0 2>/dev/null \
    | grep -v '^--' | grep -v '^$' | sort -u \
    > /tmp/scoratron_wifi_scan.txt 2>/dev/null || true
chmod 644 /tmp/scoratron_wifi_scan.txt 2>/dev/null || true

# Signal to main.py that setup mode is active
echo '{"active": true}' > "$WIFI_SETUP_FILE"
chmod 666 "$WIFI_SETUP_FILE"

# Launch AP + captive portal in background, then exit so scoratron can start
# (main.py will show the setup screen on the LED matrix)
nohup /home/admin/scoratron/wifi_setup/ap_start.sh \
    > /tmp/scoratron_wifi_setup.log 2>&1 &

exit 0
