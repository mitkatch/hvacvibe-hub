"""
Sensor Model
Holds live sensor state and per-minute daily history (00:00-23:59).
tick() simulates data — replace internals with real BLE readings.
"""
import math
import random
import datetime
from collections import deque
from models.config_model import load as cfg_load


class SensorModel:
    def __init__(self, name: str, address: str):
        self.name      = name
        self.address   = address
        self.connected = True
        self.rssi      = -65
        self.battery   = 78
        self.temp      = 24.3
        self.humidity  = 52.1
        self.vib_rms   = 0.42
        self.vib_peak  = 1.15
        self.alarm     = False
        self._t        = 0.0
        self._last_min = -1

        # Daily history: dict minute_of_day(0-1439) -> rms float
        self.history: dict[int, float] = {}
        self._prefill_history()

    def _prefill_history(self):
        now = datetime.datetime.now()
        cur = now.hour * 60 + now.minute
        t = 0.0
        for m in range(cur):
            t += 0.15
            v = max(0.01, 0.38 + 0.12 * math.sin(t * 0.9)
                    + 0.06 * math.sin(t * 3.1)
                    + random.uniform(0, 0.03))
            self.history[m] = round(v, 4)

    def tick(self):
        """Simulate live data — replace with real BLE values."""
        self._t     += 0.04
        self.vib_rms = round(max(0.01,
            0.42 + 0.12 * math.sin(self._t * 1.1)
            + 0.06 * math.sin(self._t * 3.7)
            + random.uniform(-0.02, 0.02)), 4)
        self.vib_peak  = round(self.vib_rms * 2.6 + random.uniform(-0.04, 0.04), 4)
        self.temp      = round(24.3 + 0.8 * math.sin(self._t * 0.08), 2)
        self.humidity  = round(52.1 + 1.5 * math.sin(self._t * 0.05), 2)
        self.rssi      = int(-65 + 6 * math.sin(self._t * 0.25))

        cfg = cfg_load()
        self.alarm = self.vib_rms > cfg.get('alarm_threshold', 0.6)

        # Log to daily history once per minute
        now = datetime.datetime.now()
        cur_min = now.hour * 60 + now.minute
        if cur_min != self._last_min:
            self.history[cur_min] = self.vib_rms
            self._last_min = cur_min

    def to_dict(self) -> dict:
        return {
            "name":      self.name,
            "address":   self.address,
            "connected": self.connected,
            "rssi":      self.rssi,
            "battery":   self.battery,
            "temp":      self.temp,
            "humidity":  self.humidity,
            "vib_rms":   self.vib_rms,
            "vib_peak":  self.vib_peak,
            "alarm":     self.alarm,
        }

    def history_list(self) -> list:
        """Return sorted list of [minute, rms] pairs for chart."""
        return [[m, v] for m, v in sorted(self.history.items())]


# Single sensor instance (expand to list for multi-sensor)
SENSOR = SensorModel("UNIT-01", "AA:BB:CC:DD:EE:01")
