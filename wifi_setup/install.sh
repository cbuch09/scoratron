#!/bin/bash
# install.sh — one-time setup for the Scoratron WiFi provisioning system.
# Run once as root: sudo bash /home/admin/scoratron/wifi_setup/install.sh

set -e

echo "=== Scoratron WiFi Setup Installer ==="

# 1. Install required packages
echo "[1/5] Installing hostapd and dnsmasq..."
apt-get update -qq
apt-get install -y hostapd dnsmasq

# Ensure hostapd is not masked (Pi OS sometimes masks it)
systemctl unmask hostapd 2>/dev/null || true

# 2. Make scripts executable
echo "[2/5] Setting permissions..."
chmod +x /home/admin/scoratron/wifi_setup/check_wifi.sh
chmod +x /home/admin/scoratron/wifi_setup/ap_start.sh
chmod +x /home/admin/scoratron/wifi_setup/do_connect.sh

# 3. Install systemd service
echo "[3/5] Installing systemd service..."
cp /home/admin/scoratron/wifi_setup/scoratron-wifi-setup.service \
   /etc/systemd/system/scoratron-wifi-setup.service

# 4. Add ordering to scoratron.service so it waits for the wifi check
echo "[4/5] Adding After= ordering to scoratron.service..."
mkdir -p /etc/systemd/system/scoratron.service.d
cat > /etc/systemd/system/scoratron.service.d/wifi-setup.conf << 'EOF'
[Unit]
After=scoratron-wifi-setup.service
Wants=scoratron-wifi-setup.service
EOF

mkdir -p /etc/systemd/system/scoratron-web.service.d
cat > /etc/systemd/system/scoratron-web.service.d/wifi-setup.conf << 'EOF'
[Unit]
After=scoratron-wifi-setup.service
Wants=scoratron-wifi-setup.service
EOF

# 5. Enable and reload
echo "[5/5] Enabling service..."
systemctl daemon-reload
systemctl enable scoratron-wifi-setup.service

echo ""
echo "Done! The WiFi setup service will run automatically on next boot."
echo ""
echo "To test right now (simulates no-network condition):"
echo "  1. sudo systemctl stop scoratron scoratron-web"
echo "  2. sudo bash /home/admin/scoratron/wifi_setup/ap_start.sh"
echo "  3. Connect your phone to 'Scoratron-Setup' WiFi"
echo "  4. A setup page should appear (or browse to http://192.168.4.1)"
echo ""
echo "To trigger the full flow on next boot, temporarily remove known WiFi:"
echo "  sudo nmcli connection delete <your-wifi-ssid>"
echo "  sudo reboot"
