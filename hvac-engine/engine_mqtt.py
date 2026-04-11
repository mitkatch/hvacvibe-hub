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
        # Registered message handlers: topic_pattern → callback(topic, payload)
        self._handlers: list[tuple[str, callable]] = []
        self._handlers_lock = threading.Lock()

    # ── Lifecycle ─────────────────────────────────────────────

    def start(self, config):
        self._config = config
        self._client = paho.Client(
            client_id=f"hvac-engine-{config.gateway_id}",
            clean_session=True,
        )
        self._client.on_connect    = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message    = self._on_message

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

    # ── Subscribe ─────────────────────────────────────────────

    def subscribe(self, topic: str, callback, qos: int = 1):
        """
        Subscribe to a topic pattern and register a callback.
        callback(topic: str, payload: dict) — called on each matching message.
        Safe to call before connection — subscriptions are re-applied on reconnect.
        """
        with self._handlers_lock:
            self._handlers.append((topic, callback))
        if self._connected and self._client:
            self._client.subscribe(topic, qos=qos)
            log.info(f"MQTT subscribed: {topic}")

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
            # Re-subscribe all registered handlers after (re)connect
            with self._handlers_lock:
                for topic, _ in self._handlers:
                    client.subscribe(topic, qos=1)
                    log.info(f"MQTT re-subscribed: {topic}")
        else:
            self._connected = False
            log.warning(f"MQTT connect refused rc={rc}")

    def _on_disconnect(self, client, userdata, rc):
        self._connected = False
        if rc != 0:
            log.warning(f"MQTT unexpected disconnect rc={rc} — reconnecting...")

    def _on_message(self, client, userdata, msg):
        """Route incoming messages to registered handlers."""
        try:
            payload = json.loads(msg.payload.decode())
        except Exception:
            log.warning(f"MQTT message parse error on {msg.topic}")
            return

        with self._handlers_lock:
            handlers = list(self._handlers)

        for topic_pattern, callback in handlers:
            if paho.topic_matches_sub(topic_pattern, msg.topic):
                try:
                    callback(msg.topic, payload)
                except Exception as e:
                    log.error(f"MQTT handler error for {msg.topic}: {e}")
            # paho loop_start handles reconnect automatically


# Module-level singleton
mqtt_client = EngineMQTT()
