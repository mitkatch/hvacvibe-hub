#!/usr/bin/env python3
"""
setup_main.py — HVAC-Vibe WiFi Setup Service entry point.

State machine:
  CHECKING  → does the Pi need setup?
  SETUP     → scan WiFi, start AP, Flask, show QR on display
  DONE      → WiFi already configured, exit cleanly

WiFi scan happens BEFORE AP mode starts — while wlan0 is still
connected and scanning works reliably. Results are cached and
served to the browser without needing to rescan in AP mode.

Recovery trigger files on /boot/firmware (FAT32, writable from any PC):
  hvac-reset-wifi    → force setup UI on next boot
  hvac-restore-wifi  → restore original WiFi silently on next boot
"""

import logging
import os
import subprocess
import sys
import threading
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("setup")


def main():
    from setup_wifi    import needs_setup, get_current_ip, SETUP_FLAG, scan_networks
    from setup_ap      import start_ap, stop_ap
    from setup_flask   import run_server
    from setup_display import show_setup_screen, show_success_screen, clear

    log.info("HVAC-Vibe Setup Service starting")

    # ── Check if setup is needed ───────────────────────────────────────────
    if not needs_setup():
        ip = get_current_ip()
        log.info(f"WiFi already configured (IP: {ip}) — skipping setup")
        if ip:
            try:
                show_success_screen(ip)
                time.sleep(3)
                clear()
            except Exception as e:
                log.warning(f"Display unavailable: {e}")
        sys.exit(0)

    log.info("WiFi not configured — entering setup mode")

    # ── Kill stale processes from any previous run ─────────────────────────
    for proc in ("hostapd", "dnsmasq"):
        subprocess.run(["pkill", "-f", proc], capture_output=True)
    subprocess.run(["fuser", "-k", "80/tcp"], capture_output=True)
    time.sleep(2)

    # ── Ensure NM owns wlan0 before scanning ──────────────────────────────
    subprocess.run(["nmcli", "dev", "set", "wlan0", "managed", "yes"],
                   capture_output=True)
    time.sleep(2)

    # ── Pre-scan WiFi while NM still owns wlan0 ───────────────────────────
    # Retry up to 3 times — NM may need a moment to be ready after boot.
    # Must happen BEFORE AP mode — once wlan0 switches to AP,
    # scanning other networks is unreliable.
    cached_networks = []
    for attempt in range(1, 4):
        log.info(f"Scanning available WiFi networks (attempt {attempt}/3)...")
        cached_networks = scan_networks()
        if cached_networks:
            log.info(f"Found {len(cached_networks)} networks: "
                     f"{[n['ssid'] for n in cached_networks]}")
            break
        log.warning("Scan returned 0 networks — waiting 5s before retry...")
        time.sleep(5)

    if not cached_networks:
        log.warning("No networks found after 3 attempts — continuing anyway")

    # ── Stop display services to avoid framebuffer conflict ────────────────
    for svc in ("hvac-pygame", "hvac-display", "hvac-engine"):
        result = subprocess.run(
            ["systemctl", "stop", svc], capture_output=True
        )
        if result.returncode == 0:
            log.info(f"Stopped {svc}")

    # ── Kill any stale dnsmasq ─────────────────────────────────────────────
    subprocess.run(["pkill", "-f", "dnsmasq"], capture_output=True)
    time.sleep(1)

    # ── Start AP ───────────────────────────────────────────────────────────
    if not start_ap():
        log.error("Failed to start AP — cannot proceed with setup")
        sys.exit(1)

    # ── Show QR on Waveshare display ───────────────────────────────────────
    try:
        show_setup_screen(
            ap_ssid     = "HVAC-Vibe-Setup",
            ap_password = "vibesetup",
            url         = "192.168.4.1",
        )
    except Exception as e:
        log.warning(f"Display unavailable: {e}")

    # ── Start Flask with cached networks ──────────────────────────────────
    flask_thread = threading.Thread(
        target=run_server,
        kwargs={"host": "0.0.0.0", "port": 80, "networks": cached_networks},
        daemon=True,
        name="flask-setup",
    )
    flask_thread.start()
    log.info("Setup server running at http://192.168.4.1")
    log.info("Connect to: HVAC-Vibe-Setup / vibesetup")

    # ── Wait for successful connection ─────────────────────────────────────
    log.info("Waiting for user to complete WiFi setup...")
    while True:
        if os.path.exists(SETUP_FLAG):
            ip = get_current_ip()
            log.info(f"Setup complete — IP: {ip}")
            time.sleep(4)
            stop_ap()
            log.info("Setup service done — handing off to hvac-engine")
            sys.exit(0)
        time.sleep(2)


if __name__ == "__main__":
    main()
