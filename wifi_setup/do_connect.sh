#!/bin/bash
# do_connect.sh — called by captive_portal.py after the user submits WiFi creds.
# Tears down the AP, connects to the chosen network, then reboots.
# Args: $1=SSID  $2=password (may be empty for open networks)

SSID="$1"
PASSWORD="$2"
DNSMASQ_PID="/tmp/scoratron-dnsmasq.pid"
WIFI_SETUP_FILE="/tmp/scoratron_wifi_setup.json"

echo "[do_connect] Connecting to: '$SSID'"

# Give Flask a moment to return the response to the browser
sleep 2

# --- Tear down AP ---
echo "[do_connect] Stopping AP..."
pkill hostapd 2>/dev/null || true

if [ -f "$DNSMASQ_PID" ]; then
    kill "$(cat "$DNSMASQ_PID")" 2>/dev/null || true
    rm -f "$DNSMASQ_PID"
fi

# Flush AP address (NM will reassign once we hand wlan0 back)
ip addr flush dev wlan0 2>/dev/null || true

# Clear setup flag so main.py stops showing the setup screen
echo '{"active": false}' > "$WIFI_SETUP_FILE"
chmod 666 "$WIFI_SETUP_FILE"

# Remove captive portal iptables rule
iptables -t nat -D PREROUTING -i wlan0 -p tcp --dport 80 -j DNAT --to-destination 192.168.4.1:80 2>/dev/null || true

# Restore system dnsmasq and web UI
echo "[do_connect] Restoring system dnsmasq..."
systemctl start dnsmasq 2>/dev/null || true
echo "[do_connect] Restoring scoratron-web..."
systemctl start scoratron-web 2>/dev/null || true

# --- Hand wlan0 back to NetworkManager ---
echo "[do_connect] Re-enabling NetworkManager on wlan0..."
nmcli device set wlan0 managed yes
sleep 3

# Rescan so NM knows about the chosen network
nmcli device wifi rescan ifname wlan0 2>/dev/null || true
sleep 2

# --- Connect ---
echo "[do_connect] Connecting..."
if [ -n "$PASSWORD" ]; then
    nmcli device wifi connect "$SSID" password "$PASSWORD" ifname wlan0
else
    nmcli device wifi connect "$SSID" ifname wlan0
fi

echo "[do_connect] Success. Rebooting in 3s..."
sleep 3
reboot
