"""
display_mqtt.py — MQTT subscriber for the display server.

Subscribes to hvac/{gateway_id}/# and routes messages
to display_state handlers.

Topic routing:
  .../status              → state.handle_status()
  .../environment         → state.handle_environment()
  .../vibration/fft       → state.handle_fft()
  .../vibration/features  → state.handle_features()
  .../alert               → state.handle_alert()
  .../gateway/status      → ignored (gateway health, not sensor)
"""

import json
import logging
import threading
import time

import paho.mqtt.client as paho

from display_state import state

log = logging.getLogger("display_mqtt")

_RECONNECT_DELAY = 5.0


class DisplayMQTT:
    def __init__(self):
        self._client    = None
        self._config    = None
        self._connected = False
        self._stop      = threading.Event()

    def start(self, config):
        self._config = config
        self._client = paho.Client(
            client_id=f"hvac-display-{config.gateway_id}",
            clean_session=True,
        )
        self._client.on_connect    = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message    = self._on_message

        t = threading.Thread(
            target=self._connect_loop,
            name="display-mqtt",
            daemon=True,
        )
        t.start()
        log.info(f"Display MQTT thread started → {config.mqtt_broker}:{config.mqtt_port}")

    def stop(self):
        self._stop.set()
        if self._client:
            try:
                self._client.disconnect()
                self._client.loop_stop()
            except Exception:
                pass

    # ── Internal ──────────────────────────────────────────────

    def _connect_loop(self):
        while not self._stop.is_set():
            try:
                cfg = self._config
                self._client.connect(cfg.mqtt_broker, cfg.mqtt_port, keepalive=60)
                self._client.loop_start()
                self._stop.wait()
                return
            except Exception as e:
                log.warning(f"MQTT connect failed: {e} — retry in {_RECONNECT_DELAY}s")
                self._stop.wait(timeout=_RECONNECT_DELAY)

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self._connected = True
            # Subscribe to all topics under this gateway
            topic = f"hvac/{self._config.gateway_id}/#"
            client.subscribe(topic, qos=0)
            log.info(f"MQTT connected ✓  subscribed to {topic}")
        else:
            log.warning(f"MQTT connect refused rc={rc}")

    def _on_disconnect(self, client, userdata, rc):
        self._connected = False
        if rc != 0:
            log.warning(f"MQTT disconnected rc={rc}")

    def _on_message(self, client, userdata, msg):
        topic   = msg.topic
        try:
            payload = json.loads(msg.payload.decode())
        except Exception:
            log.warning(f"Bad JSON on {topic}")
            return

        # Parse topic: hvac/{gateway_id}/{sensor_id}/{...type...}
        parts = topic.split("/")
        if len(parts) < 4:
            return

        # parts[0]=hvac, parts[1]=gateway_id, parts[2]=sensor_id, parts[3+]=type
        sensor_id  = parts[2]
        topic_type = "/".join(parts[3:])

        # Skip gateway-level topics
        if sensor_id == "gateway":
            return

        log.debug(f"← {topic_type}  {sensor_id}")

        if topic_type == "status":
            state.handle_status(sensor_id, payload)
        elif topic_type == "environment":
            state.handle_environment(sensor_id, payload)
        elif topic_type == "vibration/fft":
            state.handle_fft(sensor_id, payload)
        elif topic_type == "vibration/features":
            state.handle_features(sensor_id, payload)
        elif topic_type == "alert":
            state.handle_alert(sensor_id, payload)


# Module-level singleton
display_mqtt = DisplayMQTT()
