"""
mqtt_store.py — Drop-in replacement for data_store.

Subscribes to Mosquitto, populates SensorState objects
using the same interface as the original DataStore.
display.py imports this instead of data_store.

Topic structure:
  hvac/{gateway_id}/{sensor_id}/status
  hvac/{gateway_id}/{sensor_id}/environment
  hvac/{gateway_id}/{sensor_id}/vibration/features
  hvac/{gateway_id}/{sensor_id}/vibration/time_stats
  hvac/{gateway_id}/{sensor_id}/alert
  hvac/{gateway_id}/gateway/status   ← skipped
"""

import json
import logging
import threading
import datetime

import paho.mqtt.client as paho

from data_store import DataStore, SensorReading

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
        self._broker = broker
        self._port   = port
        self._client = None

        # Per-sensor partial data — assembled from multiple topics before flush
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

        # hvac/{gateway_id}/{sensor_id}/{type...}
        #  [0]     [1]           [2]       [3...]
        parts = topic.split("/")
        if len(parts) < 4:
            return

        sensor_id  = parts[2]   # e.g. "hvac-vibe-9aa63d"
        topic_type = "/".join(parts[3:])  # e.g. "environment", "vibration/features"

        # Skip gateway-level topics
        if sensor_id == "gateway":
            return

        # Skip $SYS topics (broker diagnostics)
        if parts[0] == "$SYS":
            return

        with self._partial_lock:
            # Init partial record for new sensor
            if sensor_id not in self._partial:
                self._partial[sensor_id] = {
                    "name":          payload.get("name", sensor_id),
                    "address":       sensor_id,
                    "connected":     False,
                    "vib_rms":       0.0,
                    "vib_peak":      0.0,
                    "dominant_hz":   0.0,
                    "temp":          0.0,
                    "humidity":      0.0,
                    "pressure":      0.0,
                    "battery":       0,
                    "rssi":          -99,
                }

            p = self._partial[sensor_id]

            # ── status ────────────────────────────────────────────────
            # {"sensor_id":..., "name":..., "connected":true,
            #  "rssi":-99, "battery":0, ...}
            if topic_type == "status":
                p["name"]      = payload.get("name",      p["name"])
                p["battery"]   = payload.get("battery",   p["battery"])
                p["rssi"]      = payload.get("rssi",      p["rssi"])
                p["connected"] = payload.get("connected", False)

                if not p["connected"]:
                    self.set_disconnected(sensor_id)
                    return

                self._flush(sensor_id, p)

            # ── environment ───────────────────────────────────────────
            # {"temp_c":23.99, "humidity":27.07,
            #  "pressure_pa":995, "pressure_hpa":9.9}  ← engine bug: hPa is wrong
            # Always use pressure_pa / 100 as the reliable source
            elif topic_type == "environment":
                p["temp"]     = payload.get("temp_c",   p["temp"])
                p["humidity"] = payload.get("humidity", p["humidity"])
                p["pressure"] = payload.get("pressure_pa", p["pressure"])
                self._flush(sensor_id, p)

            # ── vibration/features ────────────────────────────────────
            # {"vector_rms_g":0.49999, "dominant_hz":0,
            #  "rms_x_g":0.015, "rms_y_g":0.039, "rms_z_g":0.865,
            #  "crest_x":4.66, "crest_y":3.0, "crest_z":1.11, ...}
            # No peak_g field — derive peak from max(rms * crest) per axis
            elif topic_type == "vibration/features":
                p["name"]        = payload.get("name",         p["name"])
                p["vib_rms"]     = payload.get("vector_rms_g", p["vib_rms"])
                p["dominant_hz"] = payload.get("dominant_hz",  p["dominant_hz"])
                # Derive peak: highest of (rms * crest) across all three axes
                peaks = []
                for axis in ("x", "y", "z"):
                    rms   = payload.get(f"rms_{axis}_g",  0.0)
                    crest = payload.get(f"crest_{axis}",  0.0)
                    if rms > 0 and crest > 0:
                        peaks.append(rms * crest)
                if peaks:
                    p["vib_peak"] = round(max(peaks), 3)

                self._flush(sensor_id, p)

            # ── vibration/time_stats ──────────────────────────────────
            # {"rms":..., "peak":..., ...} — fallback if features absent
            elif topic_type == "vibration/time_stats":
                if p["vib_rms"] == 0.0:   # only use if features haven't arrived
                    p["vib_rms"]  = payload.get("rms",  p["vib_rms"])
                    p["vib_peak"] = payload.get("peak", p["vib_peak"])
                    self._flush(sensor_id, p)

            # ── alert ─────────────────────────────────────────────────
            # {"level":"alarm", "vib_rms":9.6, "threshold":0.6, ...}
            # No flush needed — alarm state is derived in SensorState.update()
            # from vib_rms vs ALARMS thresholds automatically.

    def _flush(self, sensor_id: str, p: dict):
        """Build a SensorReading from current partial data and push to store."""
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
