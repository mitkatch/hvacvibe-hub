#!/usr/bin/env python3
"""
HVAC-Vibe Gateway — Main entry point.
Starts all subsystem threads then runs the pygame display on the main thread.

Buttons:
  GPIO5  (BTN1) short press → cycle screens
  GPIO26 (BTN2) hold 3s     → factory reset (wipe WiFi + BLE bonds, reboot)
"""
import logging
import sys
import time

# Configure logging before importing modules
logging.basicConfig(
    level  = logging.INFO,
    format = "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt= "%H:%M:%S",
)
log = logging.getLogger("main")


def main():
    log.info("HVAC-Vibe Gateway starting...")

    # ── Start background threads ───────────────────────────────
    import ble_scanner
    import cloud_sync
    from data_store import store
    from buttons import buttons
    from screen_manager import screen_manager, screen_state

    log.info("Starting BLE scanner...")
    ble_scanner.start()

    log.info("Starting cloud sync...")
    cloud_sync.start()

    # ── Wire up buttons ────────────────────────────────────────
    def on_button1():
        sensors = store.get_all()
        screen_manager.advance(len(sensors))

    def on_button2_long():
        log.warning("RESET triggered via Button 2 long press")
        screen_state.set("reset")
        time.sleep(1.0)
        _do_reset()

    buttons.on_button1(on_button1)
    buttons.on_button2_long(on_button2_long)
    buttons.start()
    log.info("Buttons started (BTN1=GPIO5, BTN2=GPIO26)")

    # ── Run display on main thread (pygame requires main thread) ──
    log.info("Starting display...")
    try:
        import display
        display.run()
    except KeyboardInterrupt:
        log.info("Shutting down (KeyboardInterrupt)")
    except Exception as e:
        log.exception(f"Display error: {e}")
    finally:
        log.info("HVAC-Vibe Gateway stopped.")
        sys.exit(0)


def _do_reset():
    """Wipe WiFi config, BLE bonds, then reboot into AP/setup mode."""
    import os
    import subprocess

    log.info("Reset: clearing WiFi credentials...")
    try:
        wifi_conf = "/home/mitkatch/gateway/wifi.conf"
        if os.path.exists(wifi_conf):
            os.remove(wifi_conf)
            log.info(f"Removed {wifi_conf}")
    except Exception as e:
        log.warning(f"WiFi wipe error: {e}")

    log.info("Reset: clearing BLE bonds...")
    try:
        bt_base = "/var/lib/bluetooth"
        if os.path.exists(bt_base):
            for adapter in os.listdir(bt_base):
                adapter_path = os.path.join(bt_base, adapter)
                if os.path.isdir(adapter_path):
                    for device in os.listdir(adapter_path):
                        dev_path = os.path.join(adapter_path, device)
                        if os.path.isdir(dev_path) and ":" in device:
                            subprocess.run(["sudo", "rm", "-rf", dev_path],
                                           capture_output=True)
                            log.info(f"Cleared bond: {device}")
    except Exception as e:
        log.warning(f"BLE bond wipe error: {e}")

    log.info("Reset complete — rebooting...")
    time.sleep(0.5)
    os.system("sudo reboot")


if __name__ == "__main__":
    main()
