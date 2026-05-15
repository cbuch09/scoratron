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
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Barlow+Condensed:wght@400;600;700;900&display=swap" rel="stylesheet">
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: #111113; color: #f0f0f5;
      font-family: 'Barlow Condensed', sans-serif; font-weight: 400;
      min-height: 100vh; display: flex; flex-direction: column;
      align-items: center; justify-content: center; padding: 20px;
    }
    .header {
      width: 100%; max-width: 440px;
      display: flex; align-items: center; gap: 10px;
      margin-bottom: 24px;
    }
    .logo-icon { color: #7c3aed; }
    .logo-wordmark { font-family: 'Barlow Condensed', sans-serif; font-weight: 700; font-size: 20px; color: #f0f0f5; letter-spacing: 1px; }
    .card {
      background: #1c1c1f; border: 1px solid #303035; border-radius: 12px;
      padding: 28px 24px; width: 100%; max-width: 440px;
    }
    h1 {
      font-family: 'Barlow Condensed', sans-serif; font-weight: 700;
      font-size: 22px; letter-spacing: 1px; text-transform: uppercase;
      color: #f0f0f5; margin-bottom: 4px;
    }
    .sub { font-family: 'Share Tech Mono', monospace; font-size: 12px; color: #70707a; margin-bottom: 24px; }
    .form-label {
      display: block; font-family: 'Share Tech Mono', monospace;
      font-size: 11px; letter-spacing: 1px; text-transform: uppercase;
      color: #70707a; margin-bottom: 6px; margin-top: 18px;
    }
    select, input[type=text], input[type=password] {
      width: 100%; padding: 9px 12px;
      background: #26262b; color: #f0f0f5;
      border: 1px solid #303035; border-radius: 8px;
      font-family: 'Share Tech Mono', monospace; font-size: 14px;
      outline: none; transition: border-color 0.2s;
    }
    select:focus, input:focus { border-color: #7c3aed; }
    #manual_row { display: none; margin-top: 12px; }
    .btn {
      margin-top: 24px; width: 100%; padding: 12px;
      background: #7c3aed; color: #fff;
      border: 1px solid #7c3aed; border-radius: 4px;
      font-family: 'Barlow Condensed', sans-serif; font-weight: 700;
      font-size: 14px; letter-spacing: 2px; text-transform: uppercase;
      cursor: pointer; transition: box-shadow 0.2s;
    }
    .btn:hover { box-shadow: 0 0 16px rgba(124,58,237,0.4); }
    .btn:active { background: #6d28d9; }
    .msg {
      margin-top: 18px; padding: 12px 14px; border-radius: 8px;
      font-family: 'Share Tech Mono', monospace; font-size: 13px; line-height: 1.6;
    }
    .msg.ok  { background: #052e16; color: #22c55e; border: 1px solid #166534; }
    .msg.err { background: #2b0d0d; color: #ef4444; border: 1px solid #7f1d1d; }
    .hint {
      font-family: 'Share Tech Mono', monospace; font-size: 11px;
      color: #70707a; margin-top: 20px; line-height: 1.7;
    }
  </style>
</head>
<body>
<div class="header">
  <svg class="logo-icon" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>
  </svg>
  <span class="logo-wordmark">SCORATRON</span>
</div>

<div class="card">
  <h1>WiFi Setup</h1>
  <p class="sub">Connect your Scoratron to your home WiFi network.</p>

  {% if message %}
  <div class="msg {{ 'ok' if success else 'err' }}">{{ message }}</div>
  {% endif %}

  {% if not success %}
  <form method="POST" action="/connect">
    <label class="form-label">WiFi Network</label>
    <select name="ssid_select" id="ssid_select" onchange="toggleManual()">
      <option value="">— Select your network —</option>
      {% for net in networks %}
      <option value="{{ net }}">{{ net }}</option>
      {% endfor %}
      <option value="__manual__">Type manually...</option>
    </select>

    <div id="manual_row">
      <label class="form-label">Network Name (SSID)</label>
      <input type="text" name="ssid_manual" id="ssid_manual" placeholder="e.g. MyHomeWiFi" autocomplete="off">
    </div>

    <label class="form-label">Password <span style="text-transform:none;letter-spacing:0">(leave blank for open networks)</span></label>
    <input type="password" name="password" autocomplete="new-password">

    <button class="btn" type="submit">Connect &amp; Save</button>
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

@app.route('/generate_204')
@app.route('/gen_204')
def android_204():
    """Android connectivity check — return redirect instead of 204 to trigger captive portal."""
    return redirect(f'http://{AP_IP}/', 302)

@app.route('/hotspot-detect.html')
@app.route('/library/test/success.html')
def apple_hotspot():
    """iOS/macOS captive portal detection — return non-standard response to trigger portal."""
    return redirect(f'http://{AP_IP}/', 302)

@app.route('/connecttest.txt')
@app.route('/redirect')
def windows_detect():
    """Windows captive portal detection."""
    return redirect(f'http://{AP_IP}/', 302)

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def catch_all(path):
    host = request.host.split(':')[0]
    # Captive-portal detection: redirect any non-local host to the setup page.
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
