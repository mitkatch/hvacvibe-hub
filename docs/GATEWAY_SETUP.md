# HVAC-Vibe Gateway — Pi Setup & Services Reference

Reproduces the complete gateway environment on a fresh Pi Zero 2W.  
Keep this file in the repo root.

---

## Hardware

| Component | Details |
|-----------|---------|
| SBC | Raspberry Pi Zero 2W |
| Display | Waveshare 3.5" IPS SPI LCD (B) — HAT style, GPIO plug-in |
| Storage | 16 GB+ microSD (SanDisk High Endurance recommended) |
| Power | 5V 2.5A micro-USB |
| Buttons | BTN1 → GPIO5, BTN2 → GPIO26 (both pulled-up, active-low) |

---

## OS Installation

1. Flash **Raspberry Pi OS Lite 64-bit** via Raspberry Pi Imager
2. In Imager advanced settings before flashing:
   - Enable SSH
   - Set hostname: `hvacvibe`
   - Set user: `mitkatch` / your password
   - Configure WiFi SSID + password
   - Set locale/timezone (America/Toronto)
3. Boot, SSH in:
   ```bash
   ssh mitkatch@hvacvibe.local
   ```

---

## System Packages

Run in this order after first boot:

```bash
# Update
sudo apt update && sudo apt upgrade -y

# Bluetooth stack
sudo apt install -y bluetooth bluez bluez-tools

# Python runtime and pip
sudo apt install -y python3 python3-pip python3-full

# Pygame (from apt — do NOT use pip for this)
sudo apt install -y python3-pygame

# Setup mode dependencies
sudo apt install -y hostapd dnsmasq python3-flask python3-qrcode

# Misc tools
sudo apt install -y git
```

## Waveshare LCD Driver

```bash
git clone https://github.com/waveshare/LCD-show.git
cd LCD-show/
chmod +x LCD35B-show       # note: LCD (B) HAT uses LCD35B-show
sudo ./LCD35B-show
# Pi reboots automatically after this — SSH back in after ~30s
```

> **Note:** The display uses `/dev/fb1`. Pygame renders offscreen
> (`SDL_VIDEODRIVER=offscreen`) then flushes RGB565 bytes directly to
> `/dev/fb1`. SDL2 fbcon/kmsdrm are NOT used.

Also remove the redundant ads7846 overlay that conflicts on GPIO17:
```bash
sudo nano /boot/firmware/config.txt
# Remove or comment out any duplicate:  dtoverlay=ads7846,...
```

---

## Python Packages (pip)

Only one pip package is needed — everything else comes from apt:

```bash
pip3 install bleak --break-system-packages
```

---

## Bluetooth

```bash
sudo systemctl enable bluetooth
sudo systemctl start bluetooth

# Verify
bluetoothctl
  > scan on        # should discover HVACVIBE-* sensors
  > scan off
  > exit
```

---

## Service Configuration

### Disable on-demand services at boot

hostapd and dnsmasq are started dynamically by `setup_ap.py` during
setup mode. They must NOT auto-start:

```bash
sudo systemctl disable hostapd
sudo systemctl disable dnsmasq
```

---

## Application Layout on Pi

```
/home/mitkatch/
├── hvac-engine/
│   ├── venv/                    # Python venv
│   └── engine_main.py           # BLE scanner, data store, cloud sync
│
├── hvac-display/
│   ├── venv/                    # Python venv
│   └── display_main.py          # Screen state machine, button handling
│
└── hvac-pygame/
    ├── venv/                    # Python venv (runs as root for /dev/fb1)
    └── main.py                  # Pygame render loop → offscreen → /dev/fb1
```

---

## Systemd Service Files

### `/etc/systemd/system/hvac-engine.service`

```ini
[Unit]
Description=HVAC-Vibe BLE Engine
After=bluetooth.target network.target

[Service]
Type=simple
User=mitkatch
WorkingDirectory=/home/mitkatch/hvac-engine
ExecStart=/home/mitkatch/hvac-engine/venv/bin/python engine_main.py
Restart=on-failure
RestartSec=5
StandardOutput=append:/home/mitkatch/hvac-engine/engine.log
StandardError=append:/home/mitkatch/hvac-engine/engine.log

[Install]
WantedBy=multi-user.target
```

### `/etc/systemd/system/hvac-display.service`

```ini
[Unit]
Description=HVAC-Vibe Display Manager
After=hvac-engine.service

[Service]
Type=simple
User=mitkatch
WorkingDirectory=/home/mitkatch/hvac-display
ExecStart=/home/mitkatch/hvac-display/venv/bin/python display_main.py
Restart=on-failure
RestartSec=5
StandardOutput=append:/home/mitkatch/hvac-display/display.log
StandardError=append:/home/mitkatch/hvac-display/display.log

[Install]
WantedBy=multi-user.target
```

### `/etc/systemd/system/hvac-pygame.service`

```ini
[Unit]
Description=HVAC-Vibe Pygame LCD Renderer
After=hvac-engine.service

[Service]
Type=simple
User=root
WorkingDirectory=/home/mitkatch/hvac-pygame
ExecStart=/home/mitkatch/hvac-pygame/venv/bin/python main.py
Restart=on-failure
RestartSec=5
StandardOutput=append:/home/mitkatch/hvac-pygame/pygame.log
StandardError=append:/home/mitkatch/hvac-pygame/pygame.log

[Install]
WantedBy=multi-user.target
```

> **Why root for hvac-pygame?** Direct write access to `/dev/fb1`
> framebuffer requires root. The other two services run as `mitkatch`.

---

## Enable & Start All Services

After creating/editing the `.service` files above:

```bash
sudo systemctl daemon-reload
sudo systemctl enable hvac-engine hvac-display hvac-pygame
sudo systemctl start hvac-engine hvac-display hvac-pygame
```

---

## Day-to-Day Commands

```bash
# Status of all three
systemctl status hvac-engine hvac-display hvac-pygame

# Follow logs live
journalctl -u hvac-engine -f
journalctl -u hvac-display -f
journalctl -u hvac-pygame -f

# Restart one service
sudo systemctl restart hvac-pygame

# Stop all
sudo systemctl stop hvac-engine hvac-display hvac-pygame

# Check what starts at boot
systemctl list-unit-files | grep hvac

# Read the actual .service file as installed
systemctl cat hvac-pygame
```

---

## Backlight Control

```bash
# On
echo 1 | sudo tee /sys/class/backlight/backlight_gpio/brightness

# Off
echo 0 | sudo tee /sys/class/backlight/backlight_gpio/brightness
```

---

## Pygame Display Technical Notes

SDL2 on Raspberry Pi OS (Bookworm/Trixie) dropped `fbcon` driver and
KMSDRM requires EGL which isn't available on Zero 2W without a desktop.

**Solution — offscreen → fb1 pipeline:**

```python
import os
os.environ['SDL_VIDEODRIVER'] = 'offscreen'   # no display hardware needed
# ... pygame draws to in-memory surface ...
# flush_to_fb() converts RGB → RGB565 and writes to /dev/fb1
```

Display is **480×320 landscape**. Surface must be rendered at that
exact size before the flush or it will appear rotated/distorted.

---

## Quick Validation Checklist (fresh install)

```bash
# 1. Python and key packages
python3 -c "import bleak, pygame, flask, qrcode; print('imports OK')"

# 2. Bluetooth
bluetoothctl show | grep Powered   # should say: Powered: yes

# 3. Framebuffer exists
ls -la /dev/fb1                     # should exist after LCD driver install

# 4. Test pygame → fb1 pipeline (turns screen red)
python3 - << 'EOF'
import os, struct
os.environ['SDL_VIDEODRIVER'] = 'offscreen'
import pygame
pygame.init()
screen = pygame.display.set_mode((480, 320))
screen.fill((255, 0, 0))
raw = pygame.image.tostring(screen, 'RGB')
buf = bytearray(len(raw) // 3 * 2)
idx = 0
for i in range(0, len(raw), 3):
    r, g, b = raw[i], raw[i+1], raw[i+2]
    rgb565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
    buf[idx] = rgb565 & 0xFF
    buf[idx+1] = (rgb565 >> 8) & 0xFF
    idx += 2
open('/dev/fb1', 'wb').write(buf)
print("screen should be solid red")
EOF

# 5. Services running
systemctl status hvac-engine hvac-display hvac-pygame
```

---

## Package Summary

| Package | Source | Purpose |
|---------|--------|---------|
| `bluetooth bluez bluez-tools` | apt | BLE stack |
| `python3 python3-pip python3-full` | apt | Python 3.13 runtime |
| `python3-pygame` | apt | LCD rendering |
| `python3-flask` | apt | Setup mode web server |
| `python3-qrcode` | apt | QR code on display (setup mode) |
| `hostapd` | apt | WiFi AP for setup mode |
| `dnsmasq` | apt | DHCP/DNS for setup mode AP |
| `git` | apt | Clone Waveshare driver |
| `LCD-show` | git clone | Waveshare display driver |
| `bleak` | pip | BLE central library (async) |

---

## Config Files Modified

| File | Change |
|------|--------|
| `/boot/firmware/config.txt` | LCD driver appends SPI/overlay settings; remove duplicate `ads7846` dtoverlay if present |
| `/etc/systemd/system/hvac-*.service` | Three service files (see above) |

---

*Last updated: March 2026*
