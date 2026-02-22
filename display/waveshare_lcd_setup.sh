#!/bin/bash
# ============================================================
# Waveshare 3.5inch RPi LCD (G) - Setup Script
# Tested on: Raspberry Pi OS (Debian Trixie), kernel 6.12.x
# Display: ST7796S driver, XPT2046 touch, SPI interface
# ============================================================

set -e

echo "============================================"
echo " Waveshare 3.5inch LCD (G) Setup Script"
echo "============================================"
echo ""

# --- Step 1: Check running as root ---
if [ "$EUID" -ne 0 ]; then
    echo "[ERROR] Please run as root: sudo bash waveshare_lcd_setup.sh"
    exit 1
fi

# --- Step 2: Check panel-mipi-dbi is available ---
echo "[1/6] Checking kernel support..."
if modinfo panel-mipi-dbi &>/dev/null; then
    echo "      panel-mipi-dbi: FOUND"
else
    echo "[ERROR] panel-mipi-dbi kernel module not found."
    echo "        This script requires Raspberry Pi OS with kernel 6.1.21 or newer."
    exit 1
fi

# --- Step 3: Download and install ST7796S firmware ---
echo "[2/6] Installing ST7796S firmware..."
cd /tmp
wget -q --show-progress https://files.waveshare.com/wiki/common/St7796s.zip -O St7796s.zip
unzip -o -q St7796s.zip
if [ ! -f st7796s.bin ]; then
    echo "[ERROR] st7796s.bin not found after unzip"
    exit 1
fi
cp st7796s.bin /lib/firmware/
echo "      Firmware installed: /lib/firmware/st7796s.bin"

# --- Step 4: Update /boot/firmware/config.txt ---
echo "[3/6] Configuring /boot/firmware/config.txt..."
CONFIG=/boot/firmware/config.txt

# Check if already configured
if grep -q "mipi-dbi-spi" "$CONFIG"; then
    echo "      LCD config already present in config.txt, skipping."
else
    cat >> "$CONFIG" << 'EOF'

# Waveshare 3.5inch RPi LCD (G) - ST7796S
dtparam=spi=on
dtoverlay=mipi-dbi-spi,speed=48000000
dtparam=compatible=st7796s\0panel-mipi-dbi-spi
dtparam=width=320,height=480,width-mm=49,height-mm=79
dtparam=reset-gpio=27,dc-gpio=22,backlight-gpio=18
dtoverlay=ads7846,speed=2000000,penirq=17,xmin=300,ymin=300,xmax=3900,ymax=3800,pmin=0,pmax=65535,xohms=400
extra_transpose_buffer=2
EOF
    echo "      config.txt updated."
fi

# --- Step 5: Install Python dependencies ---
echo "[4/6] Installing Python dependencies..."
apt-get install -y -q python3-pil python3-numpy
echo "      Python PIL installed."

# --- Step 6: Create test pattern script ---
echo "[5/6] Creating LCD test pattern script..."
cat > /home/pi/lcd_test.py << 'PYEOF'
#!/usr/bin/env python3
# Waveshare 3.5inch LCD (G) - Test Pattern
# Writes color bars + text directly to /dev/fb1 in RGB565 format

import struct
import sys
from PIL import Image, ImageDraw

FB      = '/dev/fb1'
WIDTH   = 320
HEIGHT  = 480

def write_fb(img):
    pixels = list(img.convert('RGB').getdata())
    buf = bytearray()
    for r, g, b in pixels:
        rgb565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        buf += struct.pack('<H', rgb565)
    with open(FB, 'wb') as f:
        f.write(buf)

img  = Image.new('RGB', (WIDTH, HEIGHT))
draw = ImageDraw.Draw(img)

# Color bars
colors = ['red', 'green', 'blue', 'yellow', 'cyan', 'magenta', 'white', 'black']
bar_h  = HEIGHT // len(colors)
for i, color in enumerate(colors):
    draw.rectangle([0, i * bar_h, WIDTH, (i + 1) * bar_h], fill=color)

# Text overlay
draw.rectangle([0, 0, WIDTH, 50], fill='black')
draw.text((10, 5),  "HVAC-Vibe Gateway",  fill='white')
draw.text((10, 25), "LCD OK - Waveshare 3.5 (G)", fill='green')

write_fb(img)
print("Test pattern written to /dev/fb1")
PYEOF

# Fix ownership if pi user exists, otherwise use current sudo user
if id pi &>/dev/null; then
    chown pi:pi /home/pi/lcd_test.py
fi
chmod +x /home/pi/lcd_test.py
echo "      Script created: /home/pi/lcd_test.py"

# --- Step 7: Create systemd service ---
echo "[6/6] Installing systemd service..."

# Get the actual home directory of the invoking user
ACTUAL_USER=${SUDO_USER:-pi}
ACTUAL_HOME=$(eval echo "~$ACTUAL_USER")
LCD_SCRIPT="$ACTUAL_HOME/lcd_test.py"

# Move script to actual user home if different from /home/pi
if [ "$ACTUAL_HOME" != "/home/pi" ]; then
    mv /home/pi/lcd_test.py "$LCD_SCRIPT"
    chown "$ACTUAL_USER:$ACTUAL_USER" "$LCD_SCRIPT"
fi

cat > /etc/systemd/system/waveshare-lcd.service << SVCEOF
[Unit]
Description=Waveshare 3.5inch LCD (G) Init
After=multi-user.target

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 ${LCD_SCRIPT}
RemainAfterExit=yes
User=${ACTUAL_USER}

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable waveshare-lcd.service
echo "      Service enabled: waveshare-lcd.service"

echo ""
echo "============================================"
echo " Setup complete!"
echo " Reboot now to activate the display:"
echo "   sudo reboot"
echo ""
echo " After reboot, check status with:"
echo "   systemctl status waveshare-lcd"
echo "   ls /dev/fb1"
echo "============================================"
