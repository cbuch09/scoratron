#!/usr/bin/env python3
"""
Scoratron WiFi Setup — Captive Portal
Serves on port 80 while the Pi is in AP mode.
All DNS resolves to 192.168.4.1 (via dnsmasq catchall), so every HTTP
request from a connected device lands here, triggering captive portal
detection on Android, iOS, and Windows.
"""

import os
import subprocess
from flask import Flask, request, redirect, render_template_string

app = Flask(__name__)

AP_IP        = "192.168.4.1"
SCAN_FILE    = "/tmp/scoratron_wifi_scan.txt"
CONNECT_SCRIPT = "/home/admin/scoratron/wifi_setup/do_connect.sh"

# ── HTML template ──────────────────────────────────────────────────────────────

HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Scoratron WiFi Setup</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #0d0d0d; color: #e8e8e8;
      min-height: 100vh; display: flex; align-items: center; justify-content: center;
      padding: 20px;
    }
    .card {
      background: #1a1a1a; border: 1px solid #2e2e2e; border-radius: 12px;
      padding: 32px 28px; width: 100%; max-width: 420px;
    }
    h1 { font-size: 22px; color: #ff9900; margin-bottom: 6px; }
    .sub { color: #888; font-size: 14px; margin-bottom: 24px; }
    label { display: block; font-size: 13px; color: #aaa; margin-bottom: 4px; margin-top: 16px; }
    select, input[type=text], input[type=password] {
      width: 100%; padding: 10px 12px;
      background: #111; color: #e8e8e8;
      border: 1px solid #333; border-radius: 8px; font-size: 15px;
    }
    select:focus, input:focus { outline: none; border-color: #ff9900; }
    #manual_row { display: none; margin-top: 10px; }
    button {
      margin-top: 24px; width: 100%; padding: 13px;
      background: #ff9900; color: #000; border: none; border-radius: 8px;
      font-size: 16px; font-weight: 700; cursor: pointer;
    }
    button:active { background: #cc7700; }
    .msg {
      margin-top: 20px; padding: 12px 14px; border-radius: 8px;
      font-size: 14px; line-height: 1.5;
    }
    .msg.ok  { background: #0d2b0d; color: #6ef06e; border: 1px solid #2a6b2a; }
    .msg.err { background: #2b0d0d; color: #f06e6e; border: 1px solid #6b2a2a; }
    .hint { font-size: 12px; color: #555; margin-top: 20px; line-height: 1.6; }
  </style>
</head>
<body>
<div class="card">
  <h1>Scoratron Setup</h1>
  <p class="sub">Connect your Scoratron to your home WiFi network.</p>

  {% if message %}
  <div class="msg {{ 'ok' if success else 'err' }}">{{ message }}</div>
  {% endif %}

  {% if not success %}
  <form method="POST" action="/connect">
    <label>WiFi Network</label>
    <select name="ssid_select" id="ssid_select" onchange="toggleManual()">
      <option value="">— Select your network —</option>
      {% for net in networks %}
      <option value="{{ net }}">{{ net }}</option>
      {% endfor %}
      <option value="__manual__">Type manually...</option>
    </select>

    <div id="manual_row">
      <label>Network name (SSID)</label>
      <input type="text" name="ssid_manual" id="ssid_manual" placeholder="e.g. MyHomeWiFi" autocomplete="off">
    </div>

    <label>Password <span style="color:#555">(leave blank for open networks)</span></label>
    <input type="password" name="password" autocomplete="new-password">

    <button type="submit">Connect &amp; Save</button>
  </form>
  {% endif %}

  <p class="hint">
    After connecting, Scoratron will reboot and join your network.<br>
    Reconnect your device to your home WiFi when done.
  </p>
</div>
<script>
function toggleManual() {
  var v = document.getElementById('ssid_select').value;
  document.getElementById('manual_row').style.display = (v === '__manual__') ? 'block' : 'none';
  if (v === '__manual__') document.getElementById('ssid_manual').focus();
}
</script>
</body>
</html>
"""

# ── Helpers ────────────────────────────────────────────────────────────────────

def load_scan():
    """Return list of SSIDs collected before AP mode started."""
    try:
        with open(SCAN_FILE) as f:
            return [line.strip() for line in f if line.strip()]
    except Exception:
        return []

# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def catch_all(path):
    host = request.host.split(':')[0]
    # Captive-portal detection: redirect any non-local host to the setup page.
    # Devices make requests to known URLs (generate_204, hotspot-detect.html, etc.)
    # with the original Host header — redirecting them triggers the captive prompt.
    if host != AP_IP:
        return redirect(f'http://{AP_IP}/', 302)
    networks = load_scan()
    return render_template_string(HTML, networks=networks, message=None, success=False)

@app.route('/connect', methods=['POST'])
def connect():
    ssid = request.form.get('ssid_select', '').strip()
    if ssid == '__manual__':
        ssid = request.form.get('ssid_manual', '').strip()
    password = request.form.get('password', '').strip()

    # Basic validation — no shell injection possible since we use Popen list form
    if not ssid or len(ssid) > 64:
        networks = load_scan()
        return render_template_string(HTML, networks=networks,
                                      message="Please select or enter a valid network name.",
                                      success=False)
    if len(password) > 63:
        networks = load_scan()
        return render_template_string(HTML, networks=networks,
                                      message="Password is too long (max 63 characters).",
                                      success=False)

    # Launch do_connect.sh in background — it tears down the AP and reboots
    subprocess.Popen(['bash', CONNECT_SCRIPT, ssid, password])

    return render_template_string(HTML, networks=[],
                                  message=(
                                      f"Connecting to \"{ssid}\"... "
                                      "Scoratron will reboot in a few seconds. "
                                      "Reconnect your device to your home WiFi."
                                  ),
                                  success=True)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80, debug=False)
