#!/bin/bash
# do_connect.sh — joins the WiFi network chosen in the captive portal. No reboot.
#
# Runs as scoratron-wifi-connect.service. The portal writes the request to
# /run/scoratron-wifi-request (root-only; line 1 = SSID, line 2 = password) so
# the password never appears on a command line or in the journal.
#
# Success: hotspot stays down, the board shows its new IP.
# Failure: the hotspot comes back and the portal shows an error to retry.

set -u

REQ="/run/scoratron-wifi-request"
ERR="/tmp/scoratron_wifi_error.txt"

log() { echo "[do_connect] $*"; }

[ -f "$REQ" ] || { log "no request file"; exit 1; }
SSID=""; PASSWORD=""
{ IFS= read -r SSID; IFS= read -r PASSWORD || true; } < "$REQ"
rm -f "$REQ"
[ -n "$SSID" ] || { log "empty SSID"; exit 1; }

log "Connecting to '$SSID'"
sleep 2                                  # let the portal's reply reach the phone

systemctl stop scoratron-ap              # hotspot down (ap_stop.sh runs)

fail() {
    log "FAILED: $1"
    printf '%s' "$1" > "$ERR"; chmod 644 "$ERR"
    systemctl start --no-block scoratron-ap     # back to setup mode for a retry
    exit 1
}

# Wait for the network to show up in a scan (radio was just in AP mode)
found=0
for i in $(seq 1 6); do
    if nmcli -t -f SSID device wifi list ifname wlan0 --rescan yes 2>/dev/null \
            | sed 's/\\:/:/g' | grep -Fxq -- "$SSID"; then
        found=1; break
    fi
    sleep 2
done
[ "$found" = 1 ] && log "network visible" || log "network not seen in scan — trying as hidden"

args=(device wifi connect "$SSID" ifname wlan0)
[ -n "$PASSWORD" ] && args+=(password "$PASSWORD")
[ "$found" = 1 ] || args+=(hidden yes)

# Only clean up a profile this script creates, never one that was already saved
nmcli -t -f NAME connection show | grep -Fxq -- "$SSID" && existed=1 || existed=0

ok=0
for attempt in 1 2; do
    if out="$(nmcli --wait 45 "${args[@]}" 2>&1)"; then ok=1; log "$out"; break; fi
    log "attempt $attempt: $out"
    # Drop any half-made profile so a wrong password isn't retried forever on boot
    [ "$existed" = 1 ] || nmcli connection delete id "$SSID" >/dev/null 2>&1 || true
    sleep 3
done
[ "$ok" = 1 ] || fail "Couldn't connect to \"$SSID\". Check the password and try again."

# Wait for an address
ip=""
for i in $(seq 1 15); do
    ip="$(ip -4 -o addr show wlan0 | awk '{print $4}' | cut -d/ -f1 | head -1)"
    [ -n "$ip" ] && break
    sleep 1
done
log "connected — IP ${ip:-unknown}"
rm -f "$ERR"

# Restart the display so it shows the new IP for 10 s (same as after boot)
rm -f /tmp/scoratron_boot_ip_shown
systemctl restart scoratron
exit 0
