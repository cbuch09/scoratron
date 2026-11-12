#!/bin/bash
# ap_start.sh — puts wlan0 into WiFi-setup hotspot mode and runs the captive portal.
#
# Runs as scoratron-ap.service:  sudo systemctl restart scoratron-ap
# Started by check_wifi.sh (boot, no network) and the web UI's "Forget network".
# Teardown is ap_stop.sh (the unit's ExecStopPost), so stopping the unit always
# hands wlan0 back to normal WiFi and restarts the web UI.
#
# The hotspot is a NetworkManager "shared" connection: NM keeps owning wlan0
# the whole time (no hostapd / unmanaged hand-off), and NM's own dnsmasq does
# DHCP + the catch-all DNS from /etc/NetworkManager/dnsmasq-shared.d/.

set -u

AP_CON="Scoratron-Setup"           # NM connection name and broadcast SSID
AP_IP="192.168.4.1"
PORTAL_PY="/home/admin/scoratron/wifi_setup/captive_portal.py"
PYTHON="/home/admin/scoratron/venv/bin/python3"
SCAN_FILE="/tmp/scoratron_wifi_scan.txt"
FLAG="/tmp/scoratron_wifi_setup.json"
DNS_CONF="/etc/NetworkManager/dnsmasq-shared.d/scoratron-captive.conf"

log() { echo "[ap_start] $*"; }

echo '{"active": true}' > "$FLAG"; chmod 666 "$FLAG"

# Clean up anything left from the old hostapd-based setup
pkill -x hostapd 2>/dev/null || true
nmcli device set wlan0 managed yes 2>/dev/null || true
nmcli connection down "$AP_CON" >/dev/null 2>&1 || true

# Scan while wlan0 is still a client — the radio can't scan once it's an AP
log "Scanning for WiFi networks..."
for i in 1 2 3; do
    nmcli -t -f SSID device wifi list ifname wlan0 --rescan yes 2>/dev/null \
        | sed 's/\\:/:/g' | grep -v -e '^$' -e '^--$' | sort -u > "$SCAN_FILE.new"
    [ -s "$SCAN_FILE.new" ] && break
    sleep 2
done
if [ -s "$SCAN_FILE.new" ] || [ ! -s "$SCAN_FILE" ]; then
    mv -f "$SCAN_FILE.new" "$SCAN_FILE"
else
    rm -f "$SCAN_FILE.new"          # keep the previous non-empty scan
fi
chmod 644 "$SCAN_FILE"
log "Found $(wc -l < "$SCAN_FILE") networks"

# Catch-all DNS so phones pop up the setup page (self-healing; install.sh writes it too)
if [ ! -f "$DNS_CONF" ]; then
    mkdir -p "$(dirname "$DNS_CONF")"
    printf 'address=/#/%s\ndhcp-option=114,http://%s/\n' "$AP_IP" "$AP_IP" > "$DNS_CONF"
fi

# The stock dnsmasq service grabs port 53 on every interface, which stops NM's
# hotspot dnsmasq from starting. Nothing else uses it.
systemctl stop dnsmasq 2>/dev/null || true

# (Re)create the hotspot profile so its settings always match this script
nmcli connection delete "$AP_CON" >/dev/null 2>&1 || true
nmcli connection add type wifi ifname wlan0 con-name "$AP_CON" autoconnect no \
    ssid "$AP_CON" 802-11-wireless.mode ap 802-11-wireless.band bg 802-11-wireless.channel 6 \
    ipv4.method shared ipv4.addresses "$AP_IP/24" ipv6.method disabled >/dev/null

log "Starting hotspot '$AP_CON'..."
up=0
for attempt in 1 2 3; do
    if out="$(nmcli --wait 30 connection up "$AP_CON" 2>&1)"; then up=1; break; fi
    log "attempt $attempt failed: $out"
    sleep 3
done
if [ "$up" != 1 ]; then
    log "ERROR: hotspot would not start"
    exit 1          # ExecStopPost (ap_stop.sh) restores normal WiFi
fi
log "Hotspot up on $AP_IP"

# Free port 80 for the captive portal
systemctl stop scoratron-web 2>/dev/null || true

# Send HTTP aimed at any IP to the portal
iptables -t nat -C PREROUTING -i wlan0 -p tcp --dport 80 -j DNAT --to-destination "$AP_IP:80" 2>/dev/null \
  || iptables -t nat -A PREROUTING -i wlan0 -p tcp --dport 80 -j DNAT --to-destination "$AP_IP:80" 2>/dev/null \
  || true

log "Starting captive portal on port 80..."
exec "$PYTHON" "$PORTAL_PY"
