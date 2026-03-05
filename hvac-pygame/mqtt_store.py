"""
mqtt_store.py — Drop-in replacement for data_store.

Subscribes to Mosquitto, populates SensorState objects
using the same interface as the original DataStore.
display.py imports this instead of data_store.
"""

import json
import logging
import threading
import datetime

import paho.mqtt.client as paho

from data_store import DataStore, SensorReading, SensorState

log = logging.getLogger("mqtt_store")

MQTT_BROKER = "localhost"
MQTT_PORT   = 1883


class MQTTStore(DataStore):
    """
    DataStore subclass that populates itself from MQTT messages.
    Inherits all read methods (get_all, get_by_name, etc.) unchanged.
    """

    def __init__(self, broker=MQTT_BROKER, port=MQTT_PORT):
        super().__init__()
        self._broker  = broker
        self._port    = port
        self._client  = None
        self._gateway_id = None   # learned from first message

        # Per-sensor partial data — build SensorReading from multiple topics
        self._partial: dict[str, dict] = {}
        self._partial_lock = threading.Lock()

    def start(self):
        self._client = paho.Client(
            client_id="hvac-pygame",
            clean_session=True,
        )
        self._client.on_connect    = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message    = self._on_message

        t = threading.Thread(
            target=self._connect_loop,
            name="mqtt-store",
            daemon=True,
        )
        t.start()
        log.info(f"MQTT store connecting to {self._broker}:{self._port}")

    def _connect_loop(self):
        import time
        while True:
            try:
                self._client.connect(self._broker, self._port, keepalive=60)
                self._client.loop_forever()
                return
            except Exception as e:
                log.warning(f"MQTT connect failed: {e} — retry in 5s")
                time.sleep(5)

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            client.subscribe("hvac/#", qos=0)
            log.info("MQTT connected ✓  subscribed to hvac/#")
        else:
            log.warning(f"MQTT connect refused rc={rc}")

    def _on_disconnect(self, client, userdata, rc):
        if rc != 0:
            log.warning(f"MQTT disconnected rc={rc}")

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        try:
            payload = json.loads(msg.payload.decode())
        except Exception:
            return

        # hvac/{gateway_id}/{sensor_id}/{type}
        parts = topic.split("/")
        if len(parts) < 4:
            return

        sensor_id  = parts[2]
        topic_type = "/".join(parts[3:])

        if sensor_id == "gateway":
            return

        with self._partial_lock:
            if sensor_id not in self._partial:
                self._partial[sensor_id] = {
                    "name":     payload.get("name", sensor_id),
                    "address":  sensor_id,
                    "vib_rms":  0.0,
                    "vib_peak": 0.0,
                    "temp":     0.0,
                    "humidity": 0.0,
                    "pressure": 0.0,
                    "battery":  0,
                    "rssi":     -99,
                }

            p = self._partial[sensor_id]

            if topic_type == "status":
                p["name"]       = payload.get("name",      p["name"])
                p["vib_rms"]    = payload.get("vib_rms",   p["vib_rms"])
                p["vib_peak"]   = payload.get("vib_peak",  p["vib_peak"])
                p["battery"]    = payload.get("battery",   p["battery"])
                p["rssi"]       = payload.get("rssi",      p["rssi"])
                connected       = payload.get("connected", False)
                if not connected:
                    self.set_disconnected(sensor_id)
                    return
                self._flush(sensor_id, p)

            elif topic_type == "environment":
                p["temp"]     = payload.get("temp_c",   p["temp"])
                p["humidity"] = payload.get("humidity", p["humidity"])
                p["pressure"] = payload.get("pressure", p["pressure"])

            elif topic_type == "vibration/features":
                # x axis dominant_hz not used by display but could extend here
                pass

    def _flush(self, sensor_id: str, p: dict):
        """Build a SensorReading from partial data and update the store."""
        reading = SensorReading(
            ts        = datetime.datetime.now(),
            vib_rms   = p["vib_rms"],
            vib_peak  = p["vib_peak"],
            temp      = p["temp"],
            humidity  = p["humidity"],
            pressure  = p["pressure"],
            battery   = p["battery"],
            rssi      = p["rssi"],
        )
        self.update(
            address = p["address"],
            name    = p["name"],
            reading = reading,
        )


# Module-level singleton
store = MQTTStore()
