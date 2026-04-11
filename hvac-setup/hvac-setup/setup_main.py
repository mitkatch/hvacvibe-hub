#!/usr/bin/env python3
"""
setup_main.py — HVAC-Vibe Setup & Management daemon.

Button behavior (GPIO17):
  No press      → nothing
  1-4s release  → Management mode: Flask on local_ip:8080, QR on display
  5s+ hold      → WiFi setup mode: AP + Flask on 192.168.4.1:80, QR on display

First boot (no WiFi configured):
  Display shows "Hold button 5s to setup WiFi"
  Short press still works for management if engine is running

After WiFi connected:
  Pygame display shows IP address under HVAC-Vibe label (top-left)
  Normal engine operation continues

Recovery (SD card triggers, writable from any PC via /boot/firmware):
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

MGMT_PORT      = 8080
MGMT_TIMEOUT_S = 300    # 5 min auto-exit
ENGINE_CONFIG  = "/home/mitkatch/hvac-engine/config.json"


def get_gateway_id() -> str:
    import json
    try:
        with open(ENGINE_CONFIG) as f:
            return json.load(f).get("gateway_id", "hvacvibe")
    except Exception:
        return "hvacvibe"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--wifi-setup",  action="store_true", help="Force WiFi setup mode")
    parser.add_argument("--management",  action="store_true", help="Force management mode")
    parser.add_argument("--daemon",      action="store_true", help="Run as button-listening daemon")
    args = parser.parse_args()

    gateway_id = get_gateway_id()
    log.info(f"HVAC-Vibe Setup starting (gateway: {gateway_id})")

    # ── Initialize DB ──────────────────────────────────────────────────────
    try:
        from setup_db import setup_db
        setup_db.init()
    except Exception as e:
        log.warning(f"SetupDB init: {e}")

    # ── Force modes from CLI ───────────────────────────────────────────────
    if args.wifi_setup:
        run_wifi_setup(gateway_id)
        return

    if args.management:
        run_management(gateway_id)
        return

    # ── Daemon mode: monitor button + handle triggers ──────────────────────
    if args.daemon:
        run_daemon(gateway_id)
        return

    # ── Default: check WiFi state and act accordingly ─────────────────────
    from setup_wifi import needs_setup
    if needs_setup():
        log.info("No WiFi configured — showing setup prompt")
        show_unconfigured()
        # Button monitoring is done in daemon mode
    else:
        log.info("WiFi configured — running button daemon")
        run_daemon(gateway_id)


def show_unconfigured():
    """Show 'Hold 5s to setup' on display. Static — no flashing."""
    try:
        from setup_display import show_unconfigured_screen
        show_unconfigured_screen()
    except Exception as e:
        log.warning(f"Display unavailable: {e}")


def run_daemon(gateway_id: str):
    """
    Run as background daemon — monitor button, trigger modes on press.
    Short press (1-4s) → management mode
    Long press  (5s+)  → WiFi setup mode
    """
    from setup_button import ButtonMonitor
    from setup_wifi   import needs_setup

    log.info("Button daemon running — waiting for button press")

    # Show unconfigured screen if needed
    if needs_setup():
        show_unconfigured()

    mgmt_running  = threading.Event()
    setup_running = threading.Event()

    def on_short():
        if mgmt_running.is_set() or setup_running.is_set():
            log.info("Mode already active — ignoring short press")
            return
        mgmt_running.set()
        try:
            # Show brief "Management Mode" on display
            try:
                from setup_display import show_management_starting
                show_management_starting()
                time.sleep(1.5)
            except Exception:
                pass
            run_management(gateway_id)
        finally:
            mgmt_running.clear()

    def on_long():
        if mgmt_running.is_set() or setup_running.is_set():
            log.info("Mode already active — ignoring long press")
            return
        setup_running.set()
        try:
            run_wifi_setup(gateway_id)
        finally:
            setup_running.clear()
            # After setup, update display with new IP
            from setup_wifi import get_current_ip
            ip = get_current_ip()
            if ip:
                try:
                    from setup_display import show_ip_on_pygame
                    show_ip_on_pygame(ip)
                except Exception:
                    pass

    monitor = ButtonMonitor(
        on_short_press=lambda: threading.Thread(target=on_short, daemon=True).start(),
        on_long_press =lambda: threading.Thread(target=on_long,  daemon=True).start(),
    )
    monitor.start()

    # Keep daemon alive
    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        monitor.stop()


def run_wifi_setup(gateway_id: str):
    """AP mode WiFi setup flow."""
    from setup_wifi  import scan_networks, get_current_ip, SETUP_FLAG
    from setup_ap    import start_ap, stop_ap
    from setup_flask import run_server, get_exit_event

    log.info("=== WiFi Setup Mode ===")

    # Kill stale processes
    for proc in ("hostapd", "dnsmasq"):
        subprocess.run(["pkill", "-f", proc], capture_output=True)
    subprocess.run(["fuser", "-k", "80/tcp"], capture_output=True)
    subprocess.run(["nmcli", "dev", "set", "wlan0", "managed", "yes"],
                   capture_output=True)
    time.sleep(2)

    # Pre-scan while NM owns wlan0
    cached = []
    for attempt in range(1, 4):
        log.info(f"Scanning networks ({attempt}/3)...")
        cached = scan_networks()
        if cached:
            log.info(f"Found {len(cached)} networks")
            break
        time.sleep(5)

    # Stop engine services
    for svc in ("hvac-pygame", "hvac-display", "hvac-engine"):
        if subprocess.run(["systemctl", "stop", svc],
                          capture_output=True).returncode == 0:
            log.info(f"Stopped {svc}")

    subprocess.run(["pkill", "-f", "dnsmasq"], capture_output=True)
    time.sleep(1)

    if not start_ap():
        log.error("Failed to start AP")
        return

    # Show QR on display
    try:
        from setup_display import show_setup_screen
        show_setup_screen("HVAC-Vibe-Setup", "vibesetup", "192.168.4.1")
    except Exception as e:
        log.warning(f"Display: {e}")

    # Start Flask (WiFi setup mode)
    flask_t = threading.Thread(
        target=run_server,
        kwargs={"host": "0.0.0.0", "port": 80,
                "networks": cached, "mode": "wifi",
                "gateway_id": gateway_id},
        daemon=True, name="flask-wifi"
    )
    flask_t.start()
    log.info("WiFi setup server: http://192.168.4.1")
    log.info("AP: HVAC-Vibe-Setup / vibesetup")

    # Wait for completion
    while True:
        if os.path.exists(SETUP_FLAG):
            ip = get_current_ip()
            log.info(f"WiFi setup complete — IP: {ip}")
            time.sleep(3)
            stop_ap()

            # Restart engine services
            for svc in ("hvac-engine", "hvac-display", "hvac-pygame"):
                subprocess.run(["systemctl", "start", svc], capture_output=True)
                log.info(f"Started {svc}")

            # Show IP on pygame display
            if ip:
                time.sleep(3)   # give pygame time to start
                try:
                    from setup_display import show_ip_on_pygame
                    show_ip_on_pygame(ip)
                except Exception:
                    pass
            return
        time.sleep(2)


def run_management(gateway_id: str):
    """Management mode on local WiFi:8080."""
    from setup_wifi  import get_current_ip, scan_networks
    from setup_flask import run_server, get_exit_event

    ip = get_current_ip()
    if not ip:
        log.error("No IP — management mode unavailable")
        return

    log.info(f"=== Management Mode: http://{ip}:{MGMT_PORT} ===")

    # Kill any existing instance on 8080
    subprocess.run(["fuser", "-k", f"{MGMT_PORT}/tcp"], capture_output=True)
    time.sleep(1)

    # Show QR on display
    try:
        from setup_display import show_management_screen
        show_management_screen(ip, gateway_id)
    except Exception as e:
        log.warning(f"Display: {e}")

    # Start Flask (management mode)
    exit_event = get_exit_event()
    flask_t = threading.Thread(
        target=run_server,
        kwargs={"host": "0.0.0.0", "port": MGMT_PORT,
                "mode": "mgmt", "gateway_id": gateway_id,
                "current_ip": ip},
        daemon=True, name="flask-mgmt"
    )
    flask_t.start()
    log.info(f"Management server running")

    # Wait for exit or timeout
    exited = exit_event.wait(timeout=MGMT_TIMEOUT_S)
    log.info("Management mode exiting" + (" (user)" if exited else " (timeout)"))

    # Restore pygame display
    try:
        from setup_display import clear
        clear()
    except Exception:
        pass

    # Kill Flask
    subprocess.run(["fuser", "-k", f"{MGMT_PORT}/tcp"], capture_output=True)


if __name__ == "__main__":
    main()
