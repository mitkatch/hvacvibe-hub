#!/usr/bin/env python3
"""
HVAC-Vibe Gateway — Main entry point.
Starts all subsystem threads then runs the pygame display on the main thread.

Buttons:
  GPIO5  (BTN1) short press → cycle screens
  GPIO26 (BTN2) hold 3s     → enter setup mode (WiFi AP + web config)
"""
import logging
import sys
import time
import threading

# Configure logging before importing modules
logging.basicConfig(
    level  = logging.INFO,
    format = "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt= "%H:%M:%S",
)
log = logging.getLogger("main")


def main():
    log.info("HVAC-Vibe Gateway starting...")

    # ── Boot WiFi check ────────────────────────────────────────
    # Tests pending config (from setup page), falls back to active,
    # or signals that setup is needed.
    import wifi_manager
    wifi_status = wifi_manager.run_boot_wifi_check()
    log.info("WiFi status: %s", wifi_status)

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
        log.info("BTN2 long press — entering setup mode")
        import setup_mode
        if setup_mode.is_active():
            log.warning("Setup mode already active, ignoring")
            return
        # Run in a thread so button handler returns immediately
        threading.Thread(
            target=setup_mode.enter_setup_mode,
            args=(screen_state,),
            name="setup-mode",
            daemon=True,
        ).start()

    buttons.on_button1(on_button1)
    buttons.on_button2_long(on_button2_long)
    buttons.start()
    log.info("Buttons started (BTN1=GPIO5, BTN2=GPIO26)")

    # ── Handle SIGTERM (systemd stop, kill) same as Ctrl-C ─────
    import signal
    signal.signal(signal.SIGTERM, lambda sig, frame: sys.exit(0))

    # ── Auto-enter setup if no WiFi configured ────────────────
    if wifi_status == "needs_setup":
        log.info("No WiFi config — auto-entering setup mode")
        import setup_mode
        threading.Thread(
            target=setup_mode.enter_setup_mode,
            args=(screen_state,),
            name="setup-mode",
            daemon=True,
        ).start()

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
        log.info("Cleaning up BLE connections...")
        ble_scanner.shutdown(timeout=5.0)
        log.info("HVAC-Vibe Gateway stopped.")
        sys.exit(0)


def _do_reset():
    """Wipe WiFi config, BLE bonds, then reboot."""
    import os
    import subprocess
    import wifi_manager

    log.info("Reset: clearing WiFi credentials...")
    try:
        wifi_manager.clear_all()
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
