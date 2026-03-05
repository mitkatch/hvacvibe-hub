#!/usr/bin/env python3
"""
HVAC-Vibe pygame display.
Reads live sensor data from Mosquitto MQTT.
Runs display.py render loop on framebuffer.

No BLE, no cloud sync — just display.
"""
import logging
import signal
import sys

logging.basicConfig(
    level  = logging.INFO,
    format = "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt= "%H:%M:%S",
)
log = logging.getLogger("main")


def main():
    log.info("HVAC-Vibe pygame display starting...")

    # Start MQTT store — subscribes to hvac/# in background thread
    from mqtt_store import store
    store.start()

    # Handle SIGTERM (systemd stop)
    signal.signal(signal.SIGTERM, lambda sig, frame: sys.exit(0))

    # Run pygame display on main thread
    log.info("Starting pygame display...")
    try:
        import display
        display.run()
    except KeyboardInterrupt:
        log.info("Stopped (KeyboardInterrupt)")
    except Exception as e:
        log.exception(f"Display error: {e}")
    finally:
        log.info("HVAC-Vibe pygame display stopped.")
        sys.exit(0)


if __name__ == "__main__":
    main()
