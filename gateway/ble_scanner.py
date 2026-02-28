"""
BLE Scanner — connects to HVAC-Vibe sensors via GATT and subscribes
to burst vibration + environment notifications.

Protocol (from test_ble_receiver.py / simple_monitor.py):
  BURST_DATA_UUID  — vibration burst: N packets until 3072 bytes complete
                     each sample = 3x int16 little-endian (x, y, z)
                     scale: 4 mg/LSB
  ENV_DATA_UUID    — environment: 6 bytes big-endian
                     int16 temp (/100 = C), int16 hum (/100 = %RH),
                     uint16 press (hPa)

Runs one async task per sensor, reconnects automatically on disconnect.
Simulation mode used on Windows or when SIM_MODE=True in config.
"""

import asyncio
import logging
import math
import random
import struct
import threading
import time
import datetime

from data_store import store, SensorReading
from config import BLE, ON_PI, SIM_MODE

log = logging.getLogger("ble_scanner")

# UUIDs must match nRF52840 firmware
SERVICE_UUID    = "12345678-1234-5678-1234-56789abcdef0"
BURST_DATA_UUID = "12345678-1234-5678-1234-56789abcdef1"
ENV_DATA_UUID   = "12345678-1234-5678-1234-56789abcdef2"

SAMPLES_PER_BURST = 512
BYTES_PER_SAMPLE  = 6
EXPECTED_BYTES    = SAMPLES_PER_BURST * BYTES_PER_SAMPLE  # 3072
MG_PER_LSB        = 4
G_PER_MG          = 0.001


def compute_rms_from_burst(data: bytes):
    """Parse burst, return (rms_g, peak_g)."""
    n = len(data) // BYTES_PER_SAMPLE
    if n == 0:
        return 0.0, 0.0
    sum_sq = 0.0
    peak   = 0.0
    for i in range(n):
        x, y, z = struct.unpack_from('<hhh', data, i * BYTES_PER_SAMPLE)
        xg = x * MG_PER_LSB * G_PER_MG
        yg = y * MG_PER_LSB * G_PER_MG
        zg = z * MG_PER_LSB * G_PER_MG
        mag = math.sqrt(xg*xg + yg*yg + zg*zg)
        sum_sq += mag * mag
        if mag > peak:
            peak = mag
    return round(math.sqrt(sum_sq / n), 4), round(peak, 4)


class SensorConnection:
    def __init__(self, address, name):
        self.address    = address
        self.name       = name
        self._burst_buf = bytearray()
        self._last_env  = {}
        self._last_rssi = -99

    def on_burst(self, sender, data):
        self._burst_buf.extend(data)
        log.debug(f"{self.name} burst {len(self._burst_buf)}/{EXPECTED_BYTES}")
        if len(self._burst_buf) >= EXPECTED_BYTES:
            rms, peak = compute_rms_from_burst(bytes(self._burst_buf[:EXPECTED_BYTES]))
            log.info(f"{self.name} burst: rms={rms}g peak={peak}g")
            self._push(vib_rms=rms, vib_peak=peak)
            self._burst_buf = bytearray()

    def on_env(self, sender, data):
        if len(data) < 6:
            return
        try:
            temp_raw, hum_raw, press_raw = struct.unpack('>hhH', data[:6])
            self._last_env = {
                "temp":     round(temp_raw / 100.0, 2),
                "humidity": round(hum_raw  / 100.0, 2),
                "pressure": press_raw,
            }
            log.debug(f"{self.name} env: {self._last_env}")
            self._push(vib_rms=None, vib_peak=None)
        except struct.error as e:
            log.warning(f"{self.name} env parse: {e}")

    def _push(self, vib_rms, vib_peak):
        env    = self._last_env
        sensor = store.get_by_name(self.name)
        rms    = vib_rms  if vib_rms  is not None else (sensor.vib_rms  if sensor else 0.0)
        peak   = vib_peak if vib_peak is not None else (sensor.vib_peak if sensor else 0.0)
        store.update(self.address, self.name, SensorReading(
            ts       = datetime.datetime.now(),
            vib_rms  = rms,
            vib_peak = peak,
            temp     = env.get("temp",     0.0),
            humidity = env.get("humidity", 0.0),
            battery  = 0,
            rssi     = self._last_rssi,
        ))


async def _connect_and_monitor(address, name):
    from bleak import BleakClient
    conn = SensorConnection(address, name)
    while True:
        try:
            log.info(f"Connecting {name} ({address})...")
            async with BleakClient(address, timeout=20.0) as client:
                log.info(f"Connected: {name}")
                await client.start_notify(BURST_DATA_UUID, conn.on_burst)
                await client.start_notify(ENV_DATA_UUID,   conn.on_env)
                log.info(f"{name}: subscribed to burst+env")
                while client.is_connected:
                    await asyncio.sleep(1.0)
            store.set_disconnected(address)
            log.warning(f"{name} disconnected, retrying in 5s")
        except Exception as e:
            store.set_disconnected(address)
            log.warning(f"{name} error: {e}, retrying in 5s")
        await asyncio.sleep(5.0)


async def _discover_and_connect():
    from bleak import BleakScanner
    log.info(f"Scanning for '{BLE['device_prefix']}' devices...")
    known = set()
    while True:
        # Only scan when we have no active connections
        if not known:
            try:
                devices = await BleakScanner.discover(timeout=BLE["scan_interval"])
                for d in devices:
                    name = d.name or ""
                    if name.lower().startswith(BLE["device_prefix"].lower()):
                        if d.address not in known:
                            known.add(d.address)
                            log.info(f"Discovered {name} ({d.address})")
                            asyncio.create_task(
                                _connect_and_monitor(d.address, name))
            except Exception as e:
                log.error(f"Scan error: {e}")
        else:
            # Check if any known sensors dropped — rescan if all disconnected
            sensors = store.get_all()
            if not any(s.connected for s in sensors):
                log.info("All sensors disconnected — rescanning...")
                known.clear()
        await asyncio.sleep(BLE["scan_interval"])


# Simulation
SIM_SENSORS = [
    {"address": "AA:BB:CC:DD:EE:01", "name": "HVAC-Vibe-A1"},
    {"address": "AA:BB:CC:DD:EE:02", "name": "HVAC-Vibe-B2"},
]

def _sim_loop():
    log.info("BLE: simulation mode")
    class _Sim:
        def __init__(self, seed):
            self._t = seed
        def tick(self):
            self._t += 0.04
            t = self._t
            rms = max(0.01, 0.42 + 0.12*math.sin(t*1.1)
                      + 0.06*math.sin(t*3.7) + random.uniform(-0.02, 0.02))
            return dict(vib_rms=round(rms,4),
                        vib_peak=round(rms*2.6+random.uniform(-0.04,0.04),4),
                        temp=round(24.3+0.8*math.sin(t*0.08),2),
                        humidity=round(52.1+1.5*math.sin(t*0.05),2),
                        battery=78, rssi=int(-65+6*math.sin(t*0.25)))
    sims = [(s, _Sim(i*2.0)) for i, s in enumerate(SIM_SENSORS)]
    while True:
        now = datetime.datetime.now()
        for info, sim in sims:
            d = sim.tick()
            store.update(info["address"], info["name"], SensorReading(
                ts=now, vib_rms=d["vib_rms"], vib_peak=d["vib_peak"],
                temp=d["temp"], humidity=d["humidity"],
                battery=d["battery"], rssi=d["rssi"]))
        time.sleep(1.0)


def start():
    use_sim = SIM_MODE or not ON_PI
    if use_sim:
        t = threading.Thread(target=_sim_loop, name="ble-sim", daemon=True)
    else:
        def _run():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(_discover_and_connect())
        t = threading.Thread(target=_run, name="ble-scanner", daemon=True)
    t.start()
    log.info(f"BLE thread: {t.name}")
    return t
