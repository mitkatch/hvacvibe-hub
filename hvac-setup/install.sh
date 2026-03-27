#!/usr/bin/env bash
# install.sh — Install hvac-setup WiFi provisioning service.
#
# Run as root from the hvac-setup directory:
#   sudo bash install.sh

set -euo pipefail

SETUP_DIR="/home/mitkatch/hvac-setup"
SERVICE="hvac-setup.service"

echo "=== HVAC-Vibe Setup Service Installer ==="
echo ""

# ── System packages ────────────────────────────────────────────────────────
echo "[1/5] Installing system packages..."
apt-get update -qq
apt-get install -y \
    hostapd \
    dnsmasq \
    python3-venv \
    python3-pip

# Prevent hostapd/dnsmasq from auto-starting (we control them manually)
systemctl disable hostapd 2>/dev/null || true
systemctl disable dnsmasq 2>/dev/null || true
systemctl stop    hostapd 2>/dev/null || true
systemctl stop    dnsmasq 2>/dev/null || true

# ── Python venv ────────────────────────────────────────────────────────────
echo "[2/5] Creating Python venv..."
python3 -m venv "$SETUP_DIR/venv"
"$SETUP_DIR/venv/bin/pip" install --quiet --upgrade pip
"$SETUP_DIR/venv/bin/pip" install --quiet \
    flask \
    "qrcode[pil]" \
    pygame

# ── File permissions ───────────────────────────────────────────────────────
echo "[3/5] Setting permissions..."
chmod +x "$SETUP_DIR/setup_main.py"
chown -R mitkatch:mitkatch "$SETUP_DIR"

# ── Backup current WiFi config ─────────────────────────────────────────────
echo "[4/5] Backing up current WiFi config..."
NETWORK_CONFIG="/boot/firmware/network-config"
if [ -f "$NETWORK_CONFIG" ]; then
    cp "$NETWORK_CONFIG" "${NETWORK_CONFIG}.factory"
    echo "  Factory backup: ${NETWORK_CONFIG}.factory"
else
    echo "  Warning: $NETWORK_CONFIG not found"
fi

# ── systemd service ────────────────────────────────────────────────────────
echo "[5/5] Installing systemd service..."
cp "$SETUP_DIR/$SERVICE" "/etc/systemd/system/$SERVICE"
systemctl daemon-reload
systemctl enable "$SERVICE"

echo ""
echo "=== Installation complete ==="
echo ""
echo "Recovery options (create empty file on /boot/firmware from any PC):"
echo "  hvac-reset-wifi    → force setup UI on next boot"
echo "  hvac-restore-wifi  → restore original WiFi on next boot"
echo ""
echo "To check setup logs:"
echo "  journalctl -u hvac-setup -f"
echo ""
echo "Reboot to activate:"
echo "  sudo reboot"
