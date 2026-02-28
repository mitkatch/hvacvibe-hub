#!/usr/bin/env python3
"""
HVAC-Vibe Gateway — Main entry point.
Starts all subsystem threads then runs the pygame display on the main thread.
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

    log.info("Starting BLE scanner...")
    ble_thread = ble_scanner.start()

    log.info("Starting cloud sync...")
    sync_thread = cloud_sync.start()

    # Brief pause to let BLE scanner populate initial data
    log.info("Waiting for first sensor data...")
    time.sleep(2.0)

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


if __name__ == "__main__":
    main()
