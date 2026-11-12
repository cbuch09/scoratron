#!/bin/bash
# ap_stop.sh — ExecStopPost of scoratron-ap.service. Takes the setup hotspot
# down and puts the board back in normal mode. Safe to run more than once.

AP_CON="Scoratron-Setup"
AP_IP="192.168.4.1"

echo "[ap_stop] Stopping hotspot..."
nmcli connection down "$AP_CON" >/dev/null 2>&1 || true
while iptables -t nat -D PREROUTING -i wlan0 -p tcp --dport 80 -j DNAT --to-destination "$AP_IP:80" 2>/dev/null; do :; done

echo '{"active": false}' > /tmp/scoratron_wifi_setup.json
chmod 666 /tmp/scoratron_wifi_setup.json

systemctl start --no-block scoratron-web
exit 0
