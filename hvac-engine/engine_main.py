#!/usr/bin/env python3
"""
HVAC-Vibe Data Engine — Main entry point.

Responsibilities:
  - BLE scanning and data collection (bleak)
  - FFT / feature extraction (numpy/scipy)
  - MQTT publishing to local Mosquitto broker
  - SQLite persistence (power-loss recovery)
  - Gateway health heartbeat

Does NOT handle display, WebSocket, or HTTP.
Those are the concern of hvac-display (FastAPI).

Topic structure:
  hvac/{gateway_id}/{sensor_id}/status
  hvac/{gateway_id}/{sensor_id}/vibration/fft
  hvac/{gateway_id}/{sensor_id}/vibration/features
  hvac/{gateway_id}/{sensor_id}/environment
  hvac/{gateway_id}/{sensor_id}/alert
  hvac/{gateway_id}/gateway/status
"""

import logging
import signal
import sys
import time
import threading

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("engine")


def main():
    log.info("HVAC-Vibe Engine starting...")

    # Load config first — derives gateway_id from config.json
    from engine_config import config

    log.info(f"Gateway ID: {config.gateway_id}")
    log.info(f"MQTT broker: {config.mqtt_broker}:{config.mqtt_port}")

    # Start MQTT client — connects to local Mosquitto
    from engine_mqtt import mqtt_client
    mqtt_client.start(config)

    # Start SQLite store — recovers unsent data after power loss
    from engine_store import store
    store.init(config.db_path)

    # Start BLE scanner — discovers sensors, pushes data to processor
    from engine_ble import ble_scanner
    ble_scanner.start(config, store, mqtt_client)

    # Start gateway heartbeat — publishes Pi health every 30s
    from engine_heartbeat import heartbeat
    heartbeat.start(config, mqtt_client)

    # Graceful shutdown on SIGTERM (systemd stop)
    def _shutdown(sig, frame):
        log.info("Shutdown signal received")
        ble_scanner.stop()
        heartbeat.stop()
        mqtt_client.stop()
        log.info("Engine stopped.")
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT,  _shutdown)

    log.info("Engine running. Press Ctrl+C to stop.")
    # Keep main thread alive — all work is in daemon threads
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
