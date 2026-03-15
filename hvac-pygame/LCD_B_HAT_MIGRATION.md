# Waveshare 3.5" LCD (B) HAT — Migration Notes

Switching from the old Dupont-wire display to the Waveshare 3.5" RPi LCD (B) HAT.

---

## What Changed

The new HAT uses the `fb_ili9486` fbtft driver which registers the LCD as `/dev/fb0`
(primary framebuffer) instead of `/dev/fb1` (secondary). This means the kernel
console and getty login prompt appear on the LCD by default.

**Additional discovery (March 2026):** The kernel assigns the framebuffer number
non-deterministically at boot — the SPI display may appear as either `/dev/fb0` or
`/dev/fb1` depending on boot timing. A udev rule creates a stable `/dev/waveshare`
symlink that always points to the correct device regardless of which number the
kernel assigns. See Step 6.

---

## Steps

### 1. Install the Driver

```bash
cd ~/LCD-show
sed -i 's/\r//' LCD35B-show-V2     # fix Windows line endings
sudo ./LCD35B-show-V2               # installs driver and reboots
```

> The script will print a few harmless X11 copy errors — ignore them.
> Pi reboots automatically.

---

### 2. Remove Redundant ads7846 Overlay

The `waveshare35b-v2` overlay already includes the touch controller natively:
- `waveshare35b@0` — display (SPI0.0)
- `waveshare35b-ts@1` — ADS7846 touch controller (SPI0.1, GPIO17 interrupt)

If the LCD-show installer added a separate `dtoverlay=ads7846,...` line to
`config.txt`, **remove it** — it duplicates what the overlay already defines
and causes a GPIO17 conflict that prevents the display from loading.

```bash
sudo nano /boot/firmware/config.txt
```

The display section should look like this — nothing else:
```
dtparam=spi=on
dtoverlay=waveshare35b-v2
```

> With just the overlay, touch loads cleanly as `/dev/input/event0` and
> is available for future use. GPIO button screen cycling is preferred
> over touch for this project.

---

### 3. Update hvac-pygame config.py

`fb_device` now points to `/dev/waveshare` (the stable udev symlink from Step 6)
instead of a hardcoded fb number:

```python
DISPLAY = {
    "width":     480,
    "height":    320,
    "fps":       5,
    "fb_device": "/dev/waveshare",  # stable symlink — never changes between reboots
    "rotate":    0,                  # was 90 on old Dupont setup
    "font_mono": "Courier New" if not ON_PI else "monospace",
}
```

---

### 4. Run hvac-pygame Service as Root

The new driver creates `/dev/fb0` as `root:root 644` — not writable by regular
users. The udev rule does not stick because DRM recreates the device after udev runs.

Edit `/etc/systemd/system/hvac-pygame.service`, add under `[Service]`:

```ini
User=root
```

Reload and restart:
```bash
sudo systemctl daemon-reload
sudo systemctl restart hvac-pygame
```

---

### 5. Suppress Boot Console on LCD (optional)

By default the kernel sends boot messages and the getty login prompt to fb0.
To suppress:

```bash
sudo systemctl disable getty@tty1
```

Edit `/boot/firmware/cmdline.txt` — change `console=tty1` to `console=tty3`
and add `quiet loglevel=0` at the end:

```
console=serial0,115200 console=tty3 root=PARTUUID=... rootfstype=ext4 fsck.repair=yes rootwait cfg80211.ieee80211_regdom=CA quiet loglevel=0
```

---

### 6. Create Stable udev Symlink (REQUIRED — fixes boot-time race condition)

**Problem:** The kernel assigns `/dev/fb0` or `/dev/fb1` to the SPI display
non-deterministically depending on boot timing. Hardcoding either value in
config.py or the service file causes the display to fail on roughly 50% of
reboots.

**Solution:** A udev rule that creates `/dev/waveshare` always pointing to
whichever fb device is the `fb_ili9486` driver, regardless of number.

```bash
sudo nano /etc/udev/rules.d/99-waveshare.rules
```

Add this single line:
```
SUBSYSTEM=="graphics", ATTR{name}=="fb_ili9486", SYMLINK+="waveshare"
```

Reload udev and trigger immediately (no reboot needed):
```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Verify the symlink was created:
```bash
ls -la /dev/waveshare
# Should show: lrwxrwxrwx ... /dev/waveshare -> fb0  (or fb1 — doesn't matter)
```

**Verify after reboot** — the symlink target may change between reboots but
`/dev/waveshare` will always exist and always point to the real display device:
```bash
ls -la /dev/waveshare
ls -la /dev/fb*
```

---

### 7. Final hvac-pygame.service

The complete working service file. Key points vs the original:
- `Requires=dev-waveshare.device` and `After=...dev-waveshare.device` are **removed**
  — systemd device units don't work for symlinks, only real devices
- `ExecStartPre` polls until `/dev/waveshare` resolves to a real character device
- `SDL_FBDEV=/dev/waveshare` uses the stable symlink

```bash
sudo nano /etc/systemd/system/hvac-pygame.service
```

```ini
[Unit]
Description=HVAC-Vibe pygame Display
After=network.target mosquitto.service hvac-engine.service
Wants=mosquitto.service hvac-engine.service

[Service]
Type=simple
User=root
WorkingDirectory=/home/mitkatch/hvac-pygame
Environment=SDL_VIDEODRIVER=fbcon
Environment=SDL_FBDEV=/dev/waveshare
ExecStartPre=/bin/bash -c 'until [ -c "$(readlink -f /dev/waveshare)" ]; do sleep 1; done'
ExecStart=/home/mitkatch/hvac-pygame/venv/bin/python main.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=hvac-pygame

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl restart hvac-pygame
```

---

## Verify

After reboot:

```bash
# Check udev symlink exists and points to a real device
ls -la /dev/waveshare
readlink -f /dev/waveshare

# Check which fb number was assigned this boot
ls -la /dev/fb*

# Check driver loaded correctly
dmesg | grep -i "fb_ili9486\|fb0\|fb1"
# Should show: graphics fbX: fb_ili9486 frame buffer, 480x320

# Check service running
systemctl status hvac-pygame
journalctl -u hvac-pygame -n 20 --no-pager
```

Expected healthy output:
```
/dev/waveshare -> fb0   (or fb1 — both are correct)
crw-rw---- 1 root video 29, X /dev/fbX   ← real char device
Active: active (running)
```

---

## Troubleshooting

**Service fails with "Dependency failed"**
The service file has `Requires=dev-waveshare.device` — remove it. Systemd device
units don't work for symlinks. See Step 7 for the correct service file.

**Display shows color lines / init pattern after reboot**
The `ExecStartPre` poll ensures pygame waits for the framebuffer. If you see
color lines, check:
```bash
sudo systemctl restart hvac-pygame
ls -la /dev/waveshare
```
If waveshare symlink is missing, re-run `sudo udevadm trigger`.

**A fake regular file appears at /dev/fb0 or /dev/fb1**
Size will be exactly 307200 bytes (480×320×2). This is created when pygame
or another process tries to open a fb path that doesn't exist as a device —
it falls back to creating a regular file. Root cause is always a path mismatch.
Verify `config.py` says `"fb_device": "/dev/waveshare"` and the symlink exists.
Delete the fake file: `sudo rm /dev/fb0` or `sudo rm /dev/fb1`.

**SSH unreachable after reboot (Pi not on network)**
Try `ssh mitkatch@hvacvibe.local` — mDNS hostname is more reliable than IP.
If that fails, check router DHCP client list for a new IP. Set a static IP
in `/etc/dhcpcd.conf` to prevent this permanently:
```
interface wlan0
static ip_address=192.168.1.100/24
static routers=192.168.1.1
static domain_name_servers=192.168.1.1 8.8.8.8
```

---

## Summary of All Changes vs Old Display

| | Old (Dupont, fbtft) | New (HAT, fb_ili9486) |
|---|---|---|
| Framebuffer | `/dev/fb1` (fixed) | `/dev/fb0` or `/dev/fb1` (non-deterministic) |
| Stable device path | n/a | `/dev/waveshare` (udev symlink) |
| config.py fb_device | `/dev/fb1` | `/dev/waveshare` |
| Rotation | `90` | `0` |
| Kernel console | Goes to fb0 (HDMI, nothing) | Goes to fb0 (LCD) — suppress optionally |
| Service user | `mitkatch` | `root` |
| Service Requires | `dev-fb1.device` | none (symlinks not supported by systemd device units) |
| Service ExecStartPre | none | polls until `readlink -f /dev/waveshare` is a char device |
| SDL_FBDEV | `/dev/fb1` | `/dev/waveshare` |
| Touch overlay | `ads7846` separate line | Included in overlay — remove redundant line |
| Driver install | `LCD35B-show` | `LCD35B-show-V2` |
| udev rule | none | `/etc/udev/rules.d/99-waveshare.rules` |

---

## Why fb Number is Non-Deterministic

The kernel assigns framebuffer numbers in the order drivers initialize. On the
Pi Zero 2W the SPI display driver (`fb_ili9486`) races with other subsystems
during boot. Depending on timing it registers before or after other framebuffer
consumers, getting `fb0` or `fb1` unpredictably. The udev `SYMLINK+="waveshare"`
rule fires after device registration and creates a stable name regardless of which
number was assigned. Using `readlink -f` in the ExecStartPre poll resolves the
symlink to the actual device before testing, since `-c` does not follow symlinks
on all kernel versions.
