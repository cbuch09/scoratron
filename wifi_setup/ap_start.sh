#!/bin/bash
# ap_start.sh — configures wlan0 as an open AP and runs the captive portal.
# Called by check_wifi.sh on boot or nm-dispatcher.sh when connectivity is lost.
# Network scan is done by the caller before this script runs.

set -e

AP_IP="192.168.4.1"
HOSTAPD_CONF="/home/admin/scoratron/wifi_setup/hostapd.conf"
PORTAL_PY="/home/admin/scoratron/wifi_setup/captive_portal.py"
DNSMASQ_PID="/tmp/scoratron-dnsmasq.pid"

# Kill any leftover AP processes from a previous run
if [ -f "$DNSMASQ_PID" ]; then
    kill "$(cat "$DNSMASQ_PID")" 2>/dev/null || true
    rm -f "$DNSMASQ_PID"
fi
pkill hostapd 2>/dev/null || true
pkill -f captive_portal 2>/dev/null || true

# Scan for nearby networks while wlan0 is still under NetworkManager
# (skip if scan file was already populated by the dispatcher)
if [ ! -s /tmp/scoratron_wifi_scan.txt ]; then
    echo "[ap_start] Scanning for WiFi networks..."
    nmcli device wifi rescan ifname wlan0 2>/dev/null || true
    sleep 2
    nmcli -t -f SSID device wifi list ifname wlan0 2>/dev/null \
        | grep -v '^--' | grep -v '^$' | sort -u \
        > /tmp/scoratron_wifi_scan.txt 2>/dev/null || true
    chmod 644 /tmp/scoratron_wifi_scan.txt 2>/dev/null || true
    echo "[ap_start] Found $(wc -l < /tmp/scoratron_wifi_scan.txt) networks"
fi

echo "[ap_start] Taking wlan0 out of NetworkManager..."
nmcli device set wlan0 managed no

# Bring interface down so hostapd can take full control of the driver
ip addr flush dev wlan0
ip link set wlan0 down

echo "[ap_start] Starting hostapd..."
hostapd -B "$HOSTAPD_CONF"
sleep 2

# Add AP IP after hostapd has put the interface in AP mode.
# Do NOT run ip link set wlan0 up — hostapd already manages the link state.
ip addr add "${AP_IP}/24" dev wlan0 2>/dev/null || true

# Stop the system dnsmasq so it doesn't hold port 53 on all interfaces
echo "[ap_start] Stopping system dnsmasq..."
systemctl stop dnsmasq 2>/dev/null || true

echo "[ap_start] Starting dnsmasq (DHCP + DNS catchall)..."
dnsmasq \
    --listen-address="${AP_IP}" \
    --interface=wlan0 \
    --bind-interfaces \
    --dhcp-range=192.168.4.2,192.168.4.20,1h \
    --address=/#/${AP_IP} \
    --no-resolv \
    --pid-file="${DNSMASQ_PID}"

# Stop the web UI so port 80 is free for the captive portal
echo "[ap_start] Stopping scoratron-web to free port 80..."
systemctl stop scoratron-web 2>/dev/null || true

# Redirect all HTTP traffic from AP clients to the captive portal
echo "[ap_start] Adding iptables redirect for captive portal..."
iptables -t nat -A PREROUTING -i wlan0 -p tcp --dport 80 -j DNAT --to-destination "${AP_IP}:80" 2>/dev/null || true

echo "[ap_start] Starting captive portal on port 80..."
exec /home/admin/rgbmatrix/bin/python3 "$PORTAL_PY"
