#!/bin/bash
# ap_start.sh — configures wlan0 as an open AP and runs the captive portal.
# Called in the background by check_wifi.sh when no network is found.
# Runs until do_connect.sh kills it (via pkill on captive_portal.py).

set -e

AP_IP="192.168.4.1"
HOSTAPD_CONF="/home/admin/scoratron/wifi_setup/hostapd.conf"
PORTAL_PY="/home/admin/scoratron/wifi_setup/captive_portal.py"
DNSMASQ_PID="/tmp/scoratron-dnsmasq.pid"

echo "[ap_start] Taking wlan0 out of NetworkManager..."
nmcli device set wlan0 managed no

# Clear any existing IP and bring the interface up with a static address
ip addr flush dev wlan0
ip addr add "${AP_IP}/24" dev wlan0
ip link set wlan0 up

echo "[ap_start] Starting hostapd..."
hostapd -B "$HOSTAPD_CONF"

echo "[ap_start] Starting dnsmasq (DHCP + DNS catchall)..."
# --listen-address + --bind-interfaces ensures we don't conflict with any
# system dnsmasq that may be running on loopback or eth0.
dnsmasq \
    --listen-address="${AP_IP}" \
    --interface=wlan0 \
    --bind-interfaces \
    --dhcp-range=192.168.4.2,192.168.4.20,1h \
    --address=/#/${AP_IP} \
    --no-resolv \
    --pid-file="${DNSMASQ_PID}"

echo "[ap_start] Starting captive portal on port 80..."
exec /home/admin/rgbmatrix/bin/python3 "$PORTAL_PY"
