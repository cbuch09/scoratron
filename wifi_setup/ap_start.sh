#!/bin/bash
# ap_start.sh — configures wlan0 as an open AP and runs the captive portal.
# Called in the background by check_wifi.sh when no network is found.
# Runs until do_connect.sh kills it (via pkill on captive_portal.py).

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

# Ensure wlan0 is under NetworkManager so we can scan
echo "[ap_start] Re-enabling NetworkManager on wlan0 for scan..."
nmcli device set wlan0 managed yes
sleep 2

# Scan for nearby networks while wlan0 is in station mode
echo "[ap_start] Scanning for WiFi networks..."
nmcli device wifi rescan ifname wlan0 2>/dev/null || true
sleep 2
nmcli -t -f SSID device wifi list ifname wlan0 2>/dev/null \
    | grep -v '^--' | grep -v '^$' | sort -u \
    > /tmp/scoratron_wifi_scan.txt 2>/dev/null || true
chmod 644 /tmp/scoratron_wifi_scan.txt 2>/dev/null || true
echo "[ap_start] Found $(wc -l < /tmp/scoratron_wifi_scan.txt) networks"

echo "[ap_start] Taking wlan0 out of NetworkManager..."
nmcli device set wlan0 managed no

# Clear any existing IP and bring the interface up with a static address
ip addr flush dev wlan0
ip addr add "${AP_IP}/24" dev wlan0
ip link set wlan0 up

echo "[ap_start] Starting hostapd..."
hostapd -B "$HOSTAPD_CONF"

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
