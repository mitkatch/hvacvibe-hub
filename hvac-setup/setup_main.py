#!/usr/bin/env python3
"""
setup_main.py — HVAC-Vibe Setup & Management Service.

Two modes:
  SETUP MODE   — WiFi not configured, or button pressed on unconfigured device
                 Starts AP, serves setup UI on 192.168.4.1:80
                 Exits when WiFi connected

  MGMT MODE    — WiFi configured, button held 3s
                 Serves management UI on local IP:8080
                 Shows QR code on display
                 Exits after 5min inactivity or user clicks Exit

Button: GPIO17, hold 3 seconds

Recovery files on /boot/firmware (create from any PC via SD card):
  hvac-reset-wifi    → force WiFi setup on next boot
  hvac-restore-wifi  → restore factory WiFi silently on next boot
"""

import argparse
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

MGMT_PORT        = 8080
MGMT_TIMEOUT_S   = 300   # 5 minutes inactivity before auto-exit
GATEWAY_CONFIG   = "/home/mitkatch/hvac-engine/config.json"


def get_gateway_id() -> str:
    import json
    try:
        with open(GATEWAY_CONFIG) as f:
            return json.load(f).get("gateway_id", "roof-unit-a4b2c3")
    except Exception:
        return "roof-unit-a4b2c3"


def main():
    parser = argparse.ArgumentParser(description="HVAC-Vibe Setup & Management")
    parser.add_argument("--force-setup", action="store_true",
                        help="Force WiFi setup mode regardless of current state")
    parser.add_argument("--force-mgmt", action="store_true",
                        help="Force management mode regardless of current state")
    args = parser.parse_args()

    from setup_wifi    import needs_setup, get_current_ip, SETUP_FLAG, scan_networks
    from setup_ap      import start_ap, stop_ap
    from setup_flask   import run_server, get_exit_event
    from setup_display import (show_setup_screen, show_success_screen,
                                show_management_screen, show_unconfigured_screen, clear)
    from setup_db      import setup_db
    from setup_button  import ButtonMonitor

    gateway_id = get_gateway_id()
    log.info(f"HVAC-Vibe Setup starting (gateway: {gateway_id})")

    # ── Initialize sensor profiles DB ─────────────────────────────────────
    try:
        setup_db.init()
    except Exception as e:
        log.warning(f"SetupDB init failed: {e}")

    # ── Determine mode ─────────────────────────────────────────────────────
    wifi_needed = args.force_setup or needs_setup()

    if args.force_mgmt or (not wifi_needed):
        if wifi_needed and not args.force_mgmt:
            # No WiFi — show unconfigured screen, wait for button
            _run_unconfigured_wait(show_unconfigured_screen,
                                   lambda: _run_setup_mode(
                                       scan_networks, start_ap, stop_ap,
                                       run_server, show_setup_screen,
                                       show_success_screen, gateway_id, SETUP_FLAG
                                   ))
        else:
            # WiFi configured — run management mode
            _run_mgmt_mode(get_current_ip, run_server, get_exit_event,
                           show_management_screen, clear,
                           gateway_id, scan_networks)
    else:
        # WiFi not configured — run setup mode directly
        _run_setup_mode(scan_networks, start_ap, stop_ap, run_server,
                        show_setup_screen, show_success_screen,
                        gateway_id, SETUP_FLAG)


def _run_unconfigured_wait(show_unconfigured_screen, on_button_press):
    """Show flashing screen and wait for button press to enter setup."""
    log.info("No WiFi configured — waiting for button press")
    flash_stop = show_unconfigured_screen()

    button_pressed = threading.Event()

    def on_press():
        log.info("Button pressed — entering setup mode")
        button_pressed.set()

    from setup_button import ButtonMonitor
    monitor = ButtonMonitor(on_long_press=on_press)
    monitor.start()

    button_pressed.wait()   # block until button held 3s
    flash_stop.set()        # stop flashing display
    monitor.stop()

    on_button_press()


def _run_setup_mode(scan_networks, start_ap, stop_ap, run_server,
                    show_setup_screen, show_success_screen,
                    gateway_id, SETUP_FLAG):
    """WiFi setup flow via AP mode."""
    log.info("Entering WiFi setup mode")

    # Kill stale processes
    for proc in ("hostapd", "dnsmasq"):
        subprocess.run(["pkill", "-f", proc], capture_output=True)
    subprocess.run(["fuser", "-k", "80/tcp"], capture_output=True)
    subprocess.run(["nmcli", "dev", "set", "wlan0", "managed", "yes"],
                   capture_output=True)
    time.sleep(2)

    # Pre-scan while NM still owns wlan0
    cached_networks = []
    for attempt in range(1, 4):
        log.info(f"Scanning networks (attempt {attempt}/3)...")
        cached_networks = scan_networks()
        if cached_networks:
            log.info(f"Found {len(cached_networks)} networks")
            break
        log.warning("No networks — retrying in 5s...")
        time.sleep(5)

    # Stop engine services
    for svc in ("hvac-pygame", "hvac-display", "hvac-engine"):
        result = subprocess.run(["systemctl", "stop", svc], capture_output=True)
        if result.returncode == 0:
            log.info(f"Stopped {svc}")

    subprocess.run(["pkill", "-f", "dnsmasq"], capture_output=True)
    time.sleep(1)

    # Start AP
    if not start_ap():
        log.error("Failed to start AP")
        sys.exit(1)

    # Show QR on display
    try:
        show_setup_screen("HVAC-Vibe-Setup", "vibesetup", "192.168.4.1")
    except Exception as e:
        log.warning(f"Display unavailable: {e}")

    # Start Flask in setup mode
    flask_thread = threading.Thread(
        target=run_server,
        kwargs={"host": "0.0.0.0", "port": 80,
                "networks": cached_networks,
                "mode": "setup",
                "gateway_id": gateway_id},
        daemon=True, name="flask-setup"
    )
    flask_thread.start()
    log.info("Setup server: http://192.168.4.1")
    log.info("AP: HVAC-Vibe-Setup / vibesetup")

    # Wait for setup completion
    while True:
        if os.path.exists(SETUP_FLAG):
            from setup_wifi import get_current_ip
            ip = get_current_ip()
            log.info(f"Setup complete — IP: {ip}")
            time.sleep(4)
            stop_ap()
            log.info("Handing off to hvac-engine")
            sys.exit(0)
        time.sleep(2)


def _run_mgmt_mode(get_current_ip, run_server, get_exit_event,
                   show_management_screen, clear,
                   gateway_id, scan_networks):
    """Management mode — serve UI on local WiFi IP:8080."""
    ip = get_current_ip()
    if not ip:
        log.error("No IP available for management mode")
        sys.exit(1)

    log.info(f"Entering management mode: http://{ip}:{MGMT_PORT}")

    # Pre-scan networks for WiFi tab
    log.info("Pre-scanning networks for WiFi tab...")
    cached_networks = scan_networks()

    # Show management QR on display
    try:
        show_management_screen(ip, gateway_id)
    except Exception as e:
        log.warning(f"Display unavailable: {e}")

    # Start Flask in management mode (background)
    exit_event = get_exit_event()
    flask_thread = threading.Thread(
        target=run_server,
        kwargs={"host": "0.0.0.0", "port": MGMT_PORT,
                "networks": cached_networks,
                "mode": "mgmt",
                "gateway_id": gateway_id},
        daemon=True, name="flask-mgmt"
    )
    flask_thread.start()
    log.info(f"Management server: http://{ip}:{MGMT_PORT}")

    # Wait for exit signal or timeout
    exited = exit_event.wait(timeout=MGMT_TIMEOUT_S)
    if exited:
        log.info("Exit requested by user")
    else:
        log.info(f"Management mode timed out after {MGMT_TIMEOUT_S}s")

    # Clean up display
    try:
        clear()
    except Exception:
        pass

    log.info("Management mode done")
    sys.exit(0)


if __name__ == "__main__":
    main()
