"""
engine_mqtt.py — MQTT client wrapper around paho-mqtt.

Connects to local Mosquitto broker.
Provides publish() with automatic reconnect on failure.
Thread-safe — can be called from BLE thread, heartbeat thread, etc.
"""

import json
import logging
import threading
import time

import paho.mqtt.client as paho

log = logging.getLogger("engine_mqtt")

_RECONNECT_DELAY = 5.0   # seconds between reconnect attempts


class EngineMQTT:
    def __init__(self):
        self._client:   paho.Client | None = None
        self._lock      = threading.Lock()
        self._connected = False
        self._config    = None
        self._thread:   threading.Thread | None = None
        self._stop      = threading.Event()

    # ── Lifecycle ─────────────────────────────────────────────

    def start(self, config):
        self._config = config
        self._client = paho.Client(
            client_id=f"hvac-engine-{config.gateway_id}",
            clean_session=True,
        )
        self._client.on_connect    = self._on_connect
        self._client.on_disconnect = self._on_disconnect

        self._thread = threading.Thread(
            target=self._connect_loop,
            name="mqtt-engine",
            daemon=True,
        )
        self._thread.start()
        log.info(f"MQTT thread started → {config.mqtt_broker}:{config.mqtt_port}")

    def stop(self):
        self._stop.set()
        if self._client:
            try:
                self._client.disconnect()
                self._client.loop_stop()
            except Exception:
                pass
        log.info("MQTT stopped")

    # ── Publish ───────────────────────────────────────────────

    def publish(self, topic: str, payload: dict, qos: int = 0, retain: bool = False):
        """Serialize payload to JSON and publish. Drops silently if not connected."""
        if not self._connected:
            log.debug(f"MQTT not connected — drop {topic}")
            return False
        try:
            msg = json.dumps(payload, separators=(",", ":"))
            with self._lock:
                result = self._client.publish(topic, msg, qos=qos, retain=retain)
            if result.rc != paho.MQTT_ERR_SUCCESS:
                log.warning(f"Publish failed rc={result.rc} topic={topic}")
                return False
            log.debug(f"→ {topic}  {msg[:80]}")
            return True
        except Exception as e:
            log.warning(f"Publish error: {e}")
            return False

    @property
    def connected(self) -> bool:
        return self._connected

    # ── Internal ──────────────────────────────────────────────

    def _connect_loop(self):
        while not self._stop.is_set():
            try:
                cfg = self._config
                log.info(f"Connecting to MQTT {cfg.mqtt_broker}:{cfg.mqtt_port}...")
                self._client.connect(cfg.mqtt_broker, cfg.mqtt_port, keepalive=60)
                self._client.loop_start()
                # Wait until stop requested
                self._stop.wait()
                return
            except Exception as e:
                log.warning(f"MQTT connect failed: {e} — retry in {_RECONNECT_DELAY}s")
                self._connected = False
                self._stop.wait(timeout=_RECONNECT_DELAY)

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self._connected = True
            log.info("MQTT connected ✓")
        else:
            self._connected = False
            log.warning(f"MQTT connect refused rc={rc}")

    def _on_disconnect(self, client, userdata, rc):
        self._connected = False
        if rc != 0:
            log.warning(f"MQTT unexpected disconnect rc={rc} — reconnecting...")
            # paho loop_start handles reconnect automatically


# Module-level singleton
mqtt_client = EngineMQTT()
