# Waveshare 3.5" LCD (B) HAT — Migration Notes

Switching from the old Dupont-wire display to the Waveshare 3.5" RPi LCD (B) HAT.

---

## What Changed

The new HAT uses the `fb_ili9486` fbtft driver which registers the LCD as `/dev/fb0`
(primary framebuffer) instead of `/dev/fb1` (secondary). This means the kernel
console and getty login prompt appear on the LCD by default.

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
sudo vim /boot/firmware/config.txt
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

Two values change in `~/hvac-pygame/config.py`:

```python
DISPLAY = {
    "width":     480,
    "height":    320,
    "fps":       5,
    "fb_device": "/dev/fb0",   # was /dev/fb1
    "rotate":    0,             # was 90
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

## Verify

After reboot:

```bash
# Check driver loaded correctly
dmesg | grep -i "fb_ili9486\|fb0"
# Should show: graphics fb0: fb_ili9486 frame buffer, 480x320

# Check framebuffer device
ls -la /dev/fb0

# Check service running
systemctl status hvac-pygame
journalctl -u hvac-pygame -f
```

---

## Summary of Differences vs Old Display

| | Old (Dupont, fbtft) | New (HAT, fb_ili9486) |
|---|---|---|
| Framebuffer | `/dev/fb1` | `/dev/fb0` |
| Rotation | `90` | `0` |
| Kernel console | Goes to fb0 (HDMI, nothing) | Goes to fb0 (LCD) |
| Service user | `mitkatch` | `root` |
| Touch overlay | `ads7846` separate line | Included in overlay — remove redundant line |
| Driver install | `LCD35B-show` | `LCD35B-show-V2` |

---

## Why fb0 Instead of fb1?

The old `fbtft` driver created a **secondary** framebuffer — the kernel console
defaulted to `fb0` (HDMI) and left `fb1` free for pygame.

The new `fb_ili9486` driver registers as the **primary** display, so it becomes
`fb0`. The kernel console, getty, and lightdm all target it by default.
The pygame `flush_to_fb()` code is unchanged — it still writes raw RGB565 bytes
directly to the framebuffer device path defined in `config.py`.
