"""
setup_mqtt_cmd.py — MQTT command/ack protocol between hvac-setup and hvac-engine.

Command flow:
  hvac-setup publishes  → hvac/{gateway_id}/commands/sensor/{sensor_id}
  hvac-engine subscribes, executes (BLE NUS write), publishes ack
  hvac-setup waits for  → hvac/{gateway_id}/commands/sensor/{sensor_id}/ack

Supported commands:
  rename  — set display name on sensor firmware via BLE NUS
"""

import json
import logging
import threading
import time
import uuid

import paho.mqtt.client as paho

log = logging.getLogger("setup_mqtt_cmd")

MQTT_BROKER  = "localhost"
MQTT_PORT    = 1883
ACK_TIMEOUT  = 10   # seconds to wait for engine ack


class MQTTCommander:
    """
    Lightweight MQTT client for sending commands and waiting for acks.
    Separate from the display's MQTTStore — this is command-only.
    """

    def __init__(self, gateway_id: str,
                 broker: str = MQTT_BROKER, port: int = MQTT_PORT):
        self._gateway_id = gateway_id
        self._broker     = broker
        self._port       = port
        self._client     = None
        self._connected  = threading.Event()
        # Pending acks: request_id → threading.Event
        self._pending: dict[str, dict] = {}
        self._pending_lock = threading.Lock()

    def start(self):
        self._client = paho.Client(
            client_id=f"hvac-setup-cmd-{uuid.uuid4().hex[:6]}",
            clean_session=True,
        )
        self._client.on_connect    = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message    = self._on_message

        self._client.connect(self._broker, self._port, keepalive=30)
        self._client.loop_start()

        if not self._connected.wait(timeout=5):
            log.error("MQTT commander failed to connect")
            return False
        log.info("MQTT commander connected")
        return True

    def stop(self):
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            # Subscribe to all sensor ack topics
            ack_topic = f"hvac/{self._gateway_id}/commands/sensor/+/ack"
            client.subscribe(ack_topic, qos=1)
            log.info(f"MQTT commander subscribed to {ack_topic}")
            self._connected.set()
        else:
            log.error(f"MQTT commander connect failed rc={rc}")

    def _on_disconnect(self, client, userdata, rc):
        if rc != 0:
            log.warning(f"MQTT commander disconnected rc={rc}")
        self._connected.clear()

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
        except Exception:
            return

        request_id = payload.get("request_id")
        if not request_id:
            return

        with self._pending_lock:
            if request_id in self._pending:
                self._pending[request_id]["result"] = payload
                self._pending[request_id]["event"].set()
                log.info(f"Ack received: request_id={request_id} "
                         f"success={payload.get('success')}")

    # ── Commands ───────────────────────────────────────────────────────────

    def rename_sensor(self, sensor_id: str, display_name: str) -> dict:
        """
        Send rename command to engine → engine writes via BLE NUS.
        Returns ack dict with success/failure, or timeout dict.
        """
        request_id = uuid.uuid4().hex[:8]
        topic      = f"hvac/{self._gateway_id}/commands/sensor/{sensor_id}"

        payload = {
            "cmd":          "rename",
            "sensor_id":    sensor_id,
            "display_name": display_name,
            "request_id":   request_id,
            "ts":           int(time.time()),
        }

        # Register pending ack before publishing
        event = threading.Event()
        with self._pending_lock:
            self._pending[request_id] = {"event": event, "result": None}

        self._client.publish(topic, json.dumps(payload), qos=1)
        log.info(f"Sent rename command: sensor={sensor_id} "
                 f"name={display_name!r} request_id={request_id}")

        # Wait for ack
        if event.wait(timeout=ACK_TIMEOUT):
            with self._pending_lock:
                result = self._pending.pop(request_id)["result"]
            return result
        else:
            with self._pending_lock:
                self._pending.pop(request_id, None)
            log.warning(f"Rename ack timed out: request_id={request_id}")
            return {
                "request_id": request_id,
                "success":    False,
                "error":      "timeout — sensor may be disconnected",
            }


# ── Gateway ID helper ──────────────────────────────────────────────────────

def get_gateway_id(config_path: str = "/home/mitkatch/hvac-engine/config.json") -> str:
    import json as _json
    try:
        with open(config_path) as f:
            return _json.load(f).get("gateway_id", "roof-unit-a4b2c3")
    except Exception:
        return "roof-unit-a4b2c3"
