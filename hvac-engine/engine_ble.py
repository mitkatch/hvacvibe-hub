"""
engine_ble.py — BLE scanner and sensor connection manager.

Discovers HVAC-Vibe sensors, connects via GATT, subscribes to:
  - BURST_DATA_UUID  → vibration burst (512 × 3-axis int16)
  - ENV_DATA_UUID    → BME280 environment (temp, humidity, pressure)

On each complete burst → calls engine_processor → publishes FFT + features.
On each env update    → publishes environment topic.
After each burst      → publishes status topic.
On alarm change       → publishes alert topic.

Runs one async task per sensor. Reconnects automatically.
Simulation mode available (SIM_MODE=True in config.json).
"""

import asyncio
import datetime
import logging
import math
import random
import struct
import threading
import time

log = logging.getLogger("engine_ble")

# BLE packet constants — must match firmware
BYTES_PER_SAMPLE  = 6
EXPECTED_BYTES    = 512 * BYTES_PER_SAMPLE   # 3072 bytes per burst


def _sensor_id_from_mac(name: str, address: str) -> str:
    """
    Derive sensor_id = sanitized-name + last-3-bytes-of-MAC.
    e.g. "HVAC-Vibe-A1" + "AA:BB:CC:DD:EE:01" → "hvac-vibe-a1-ddee01"
    """
    import re
    mac_suffix = address.replace(":", "")[-6:].lower()
    safe_name  = re.sub(r"[^a-zA-Z0-9_\-]", "-", name).lower().strip("-")[:20]
    return f"{safe_name}-{mac_suffix}"


class SensorSession:
    """
    Manages the GATT session for one sensor.
    Accumulates burst packets, calls processor, publishes MQTT.
    """
    def __init__(self, address: str, name: str, sensor_id: str,
                 config, store, mqtt_client):
        self.address   = address
        self.name      = name
        self.sensor_id = sensor_id
        self._config   = config
        self._store    = store
        self._mqtt     = mqtt_client

        self._burst_buf  = bytearray()
        self._last_env   = {}
        self._last_vib   = {}        # last processed vibration summary
        self._prev_alarm = False     # track alarm state changes

    # ── GATT notification handlers ────────────────────────────

    def on_burst(self, sender, data: bytes):
        self._burst_buf.extend(data)
        if len(self._burst_buf) >= EXPECTED_BYTES:
            burst = bytes(self._burst_buf[:EXPECTED_BYTES])
            self._burst_buf = bytearray()
            self._handle_burst(burst)

    def on_env(self, sender, data: bytes):
        if len(data) < 6:
            return
        try:
            temp_raw, hum_raw, press_raw = struct.unpack(">hhH", data[:6])
            self._last_env = {
                "temp_c":     round(temp_raw / 100.0, 2),
                "humidity":   round(hum_raw  / 100.0, 2),
                "pressure":   press_raw,
            }
            self._publish_environment()
        except struct.error as e:
            log.warning(f"{self.name} env parse error: {e}")

    # ── Processing pipeline ───────────────────────────────────

    def _handle_burst(self, burst: bytes):
        from engine_processor import process_burst

        log.debug(f"{self.name}: processing burst {len(burst)} bytes")
        summary = process_burst(
            burst, self.sensor_id, self._config, self._mqtt
        )
        if not summary:
            return

        self._last_vib = summary
        self._store.update_sensor(self.sensor_id, self.name, self.address,
                                  summary, self._last_env)
        self._publish_status(connected=True)
        self._check_alert(summary)

    def _publish_status(self, connected: bool):
        import time
        vib  = self._last_vib
        env  = self._last_env
        self._mqtt.publish(
            topic=self._config.topic(self.sensor_id, "status"),
            payload={
                "ts":        int(time.time()),
                "sensor_id": self.sensor_id,
                "name":      self.name,
                "connected": connected,
                "rssi":      self._store.get_rssi(self.sensor_id),
                "battery":   self._store.get_battery(self.sensor_id),
                "vib_rms":   vib.get("vib_rms",  0.0),
                "vib_peak":  vib.get("vib_peak", 0.0),
                "alarm":     vib.get("alarm", False),
                "warn":      vib.get("warn",  False),
                "temp_c":    env.get("temp_c",   0.0),
                "humidity":  env.get("humidity", 0.0),
            },
            qos=0,
            retain=True,     # retain so display gets last state on connect
        )

    def _publish_environment(self):
        import time
        env = self._last_env
        self._mqtt.publish(
            topic=self._config.topic(self.sensor_id, "environment"),
            payload={
                "ts":       int(time.time()),
                "temp_c":   env.get("temp_c",   0.0),
                "humidity": env.get("humidity", 0.0),
                "pressure": env.get("pressure", 0),
            },
            qos=0,
        )

    def _check_alert(self, summary: dict):
        from engine_config import ALARMS
        import time

        alarm = summary.get("alarm", False)
        warn  = summary.get("warn",  False)

        # Only publish alert on state change (avoid flooding)
        if alarm != self._prev_alarm:
            level = "alarm" if alarm else ("warn" if warn else "ok")
            self._mqtt.publish(
                topic=self._config.topic(self.sensor_id, "alert"),
                payload={
                    "ts":        int(time.time()),
                    "sensor_id": self.sensor_id,
                    "level":     level,
                    "vib_rms":   summary["vib_rms"],
                    "threshold": ALARMS["vib_rms_alarm"] if alarm
                                 else ALARMS["vib_rms_warn"],
                    "dominant_hz": summary.get("dominant_hz", 0.0),
                },
                qos=1,    # alerts are important
                retain=True,
            )
            log.info(f"{self.name}: alert level={level} rms={summary['vib_rms']:.3f}g")
            self._prev_alarm = alarm

    def publish_disconnected(self):
        import time
        self._mqtt.publish(
            topic=self._config.topic(self.sensor_id, "status"),
            payload={
                "ts":        int(time.time()),
                "sensor_id": self.sensor_id,
                "name":      self.name,
                "connected": False,
            },
            qos=0,
            retain=True,
        )


# ── BLE async tasks ───────────────────────────────────────────

async def _connect_and_monitor(address: str, name: str, sensor_id: str,
                                config, store, mqtt_client):
    from bleak import BleakClient
    from engine_config import SERVICE_UUID, BURST_DATA_UUID, ENV_DATA_UUID

    session = SensorSession(address, name, sensor_id, config, store, mqtt_client)

    while True:
        try:
            log.info(f"Connecting to {name} ({address})...")
            async with BleakClient(address, timeout=config.BLE["connect_timeout"]) as client:
                log.info(f"Connected: {name}")
                await client.start_notify(BURST_DATA_UUID, session.on_burst)
                await client.start_notify(ENV_DATA_UUID,   session.on_env)
                log.info(f"{name}: subscribed to burst + env")
                while client.is_connected:
                    await asyncio.sleep(1.0)

            session.publish_disconnected()
            log.warning(f"{name}: disconnected — retrying in {config.BLE['retry_delay']}s")

        except asyncio.CancelledError:
            session.publish_disconnected()
            return
        except Exception as e:
            session.publish_disconnected()
            log.warning(f"{name}: error {e} — retrying in {config.BLE['retry_delay']}s")

        await asyncio.sleep(config.BLE["retry_delay"])


async def _scan_loop(config, store, mqtt_client):
    from bleak import BleakScanner

    known = set()   # sensor_ids with active tasks

    while True:
        try:
            log.info("Scanning for HVAC-Vibe sensors...")
            devices = await BleakScanner.discover(timeout=config.BLE["scan_interval"])
            for d in devices:
                dname = d.name or ""
                if dname.lower().startswith(config.BLE["device_prefix"].lower()):
                    sensor_id = _sensor_id_from_mac(dname, d.address)
                    if sensor_id not in known:
                        known.add(sensor_id)
                        log.info(f"Discovered: {dname} ({d.address}) → {sensor_id}")
                        asyncio.create_task(
                            _connect_and_monitor(
                                d.address, dname, sensor_id,
                                config, store, mqtt_client
                            )
                        )
        except Exception as e:
            log.error(f"Scan error: {e}")

        await asyncio.sleep(config.BLE["scan_interval"])


# ── Simulation ────────────────────────────────────────────────

_SIM_SENSORS = [
    {"address": "AA:BB:CC:DD:EE:01", "name": "HVAC-Vibe-A1"},
    {"address": "AA:BB:CC:DD:EE:02", "name": "HVAC-Vibe-B2"},
]


def _sim_loop(config, store, mqtt_client):
    """
    Simulation: generate realistic vibration + env data without BLE hardware.
    Publishes the same MQTT topics as real sensors.
    """
    import numpy as np
    from engine_processor import process_burst
    import time

    log.info("BLE: simulation mode")

    sessions = []
    for s in _SIM_SENSORS:
        sid     = _sensor_id_from_mac(s["name"], s["address"])
        session = SensorSession(
            s["address"], s["name"], sid, config, store, mqtt_client
        )
        sessions.append((s, session, sid))
        log.info(f"Sim sensor: {s['name']} → {sid}")

    t = 0.0
    while True:
        time.sleep(10.0)    # one burst every 10s (matches firmware)
        t += 10.0

        for info, session, sid in sessions:
            # Simulate 512 samples at 1600 Hz with a 30 Hz motor fundamental
            n       = 512
            ts_arr  = np.arange(n) / 1600.0
            rms_mod = 0.42 + 0.12 * math.sin(t * 0.07)
            noise   = np.random.normal(0, 0.01, n)

            x = (rms_mod * np.sin(2*math.pi*30*ts_arr) +
                 0.15    * np.sin(2*math.pi*60*ts_arr) +
                 0.05    * np.sin(2*math.pi*90*ts_arr) + noise)
            y = (rms_mod * 0.7 * np.sin(2*math.pi*30*ts_arr + 0.4) + noise * 0.8)
            z = (0.1 * np.ones(n) + noise * 0.5)

            # Pack as int16 little-endian, same format as ADXL343 firmware
            scale = 1.0 / (4 * 0.001)   # inverse of MG_PER_LSB * G_PER_MG
            raw   = np.column_stack([
                (x * scale).astype(np.int16),
                (y * scale).astype(np.int16),
                (z * scale).astype(np.int16),
            ])
            burst = raw.astype("<i2").tobytes()

            # Inject env data
            env_temp  = round(24.3 + 0.8 * math.sin(t * 0.05), 2)
            env_hum   = round(52.1 + 1.5 * math.sin(t * 0.03), 2)
            session._last_env = {
                "temp_c":   env_temp,
                "humidity": env_hum,
                "pressure": 1013,
            }
            session._publish_environment()

            # Run full pipeline
            session._handle_burst(burst)


# ── Public API ────────────────────────────────────────────────

class BLEScanner:
    def __init__(self):
        self._thread = None
        self._loop   = None
        self._stop   = threading.Event()

    def start(self, config, store, mqtt_client):
        if config.sim_mode:
            self._thread = threading.Thread(
                target=_sim_loop,
                args=(config, store, mqtt_client),
                name="ble-sim",
                daemon=True,
            )
        else:
            def _run():
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
                self._loop.run_until_complete(
                    _scan_loop(config, store, mqtt_client)
                )
            self._thread = threading.Thread(
                target=_run,
                name="ble-scanner",
                daemon=True,
            )
        self._thread.start()
        log.info(f"BLE thread started: {self._thread.name}")

    def stop(self):
        self._stop.set()
        if self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._loop.stop)
        log.info("BLE scanner stopped")


# Module-level singleton
ble_scanner = BLEScanner()
