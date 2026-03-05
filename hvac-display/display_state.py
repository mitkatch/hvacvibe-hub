"""
display_state.py — In-memory live sensor state.

Built from incoming MQTT messages. Thread-safe.
Holds latest values per sensor_id for WebSocket broadcast.
Also caches last 3 FFT results per axis per sensor.
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("display_state")


@dataclass
class FFTData:
    frequencies: list = field(default_factory=list)
    amplitudes:  list = field(default_factory=list)


@dataclass
class SensorLiveState:
    sensor_id:   str
    name:        str        = "Unknown"
    connected:   bool       = False
    vib_rms:     float      = 0.0
    vib_peak:    float      = 0.0
    dominant_hz: float      = 0.0
    alarm:       bool       = False
    warn:        bool       = False
    temp_c:      float      = 0.0
    humidity:    float      = 0.0
    pressure:    int        = 0
    battery:     int        = 0
    rssi:        int        = -99
    last_seen:   float      = 0.0
    alert_level: str        = "ok"   # "ok" | "warn" | "alarm"

    # Latest FFT per axis — updated on each vibration/fft message
    fft_x: FFTData = field(default_factory=FFTData)
    fft_y: FFTData = field(default_factory=FFTData)
    fft_z: FFTData = field(default_factory=FFTData)

    def to_dict(self) -> dict:
        return {
            "sensor_id":   self.sensor_id,
            "name":        self.name,
            "connected":   self.connected,
            "vib_rms":     self.vib_rms,
            "vib_peak":    self.vib_peak,
            "dominant_hz": self.dominant_hz,
            "alarm":       self.alarm,
            "warn":        self.warn,
            "temp_c":      self.temp_c,
            "humidity":    self.humidity,
            "pressure":    self.pressure,
            "battery":     self.battery,
            "rssi":        self.rssi,
            "last_seen":   self.last_seen,
            "alert_level": self.alert_level,
            "fft": {
                "x": {"frequencies": self.fft_x.frequencies,
                       "amplitudes":  self.fft_x.amplitudes},
                "y": {"frequencies": self.fft_y.frequencies,
                       "amplitudes":  self.fft_y.amplitudes},
                "z": {"frequencies": self.fft_z.frequencies,
                       "amplitudes":  self.fft_z.amplitudes},
            },
        }


class DisplayState:
    def __init__(self):
        self._lock    = threading.RLock()
        self._sensors: dict[str, SensorLiveState] = {}
        self._on_change = None   # callback → triggers WebSocket broadcast

    def set_on_change(self, fn):
        """Register callback fired whenever state changes."""
        self._on_change = fn

    # ── MQTT message handlers ─────────────────────────────────

    def handle_status(self, sensor_id: str, payload: dict):
        with self._lock:
            s = self._get_or_create(sensor_id, payload.get("name", sensor_id))
            s.connected   = payload.get("connected", False)
            s.name        = payload.get("name", s.name)
            s.vib_rms     = payload.get("vib_rms",  s.vib_rms)
            s.vib_peak    = payload.get("vib_peak", s.vib_peak)
            s.alarm       = payload.get("alarm",    s.alarm)
            s.warn        = payload.get("warn",     s.warn)
            s.temp_c      = payload.get("temp_c",   s.temp_c)
            s.humidity    = payload.get("humidity", s.humidity)
            s.battery     = payload.get("battery",  s.battery)
            s.rssi        = payload.get("rssi",     s.rssi)
            s.last_seen   = payload.get("ts", time.time())
        self._notify()

    def handle_environment(self, sensor_id: str, payload: dict):
        with self._lock:
            s = self._get_or_create(sensor_id)
            s.temp_c    = payload.get("temp_c",   s.temp_c)
            s.humidity  = payload.get("humidity", s.humidity)
            s.pressure  = payload.get("pressure", s.pressure)
        self._notify()

    def handle_fft(self, sensor_id: str, payload: dict):
        axis = payload.get("axis", "x")
        freqs = payload.get("frequencies", [])
        amps  = payload.get("amplitudes",  [])
        with self._lock:
            s = self._get_or_create(sensor_id)
            fft = FFTData(frequencies=freqs, amplitudes=amps)
            if axis == "x":
                s.fft_x = fft
            elif axis == "y":
                s.fft_y = fft
            elif axis == "z":
                s.fft_z = fft
        self._notify()

    def handle_features(self, sensor_id: str, payload: dict):
        with self._lock:
            s = self._get_or_create(sensor_id)
            x = payload.get("x", {})
            s.dominant_hz = x.get("dominant_hz", s.dominant_hz)
        # No notify — features don't drive UI directly

    def handle_alert(self, sensor_id: str, payload: dict):
        with self._lock:
            s = self._get_or_create(sensor_id)
            s.alert_level = payload.get("level", "ok")
            s.alarm = s.alert_level == "alarm"
            s.warn  = s.alert_level == "warn"
        self._notify()

    # ── Read ──────────────────────────────────────────────────

    def get_all(self) -> list[SensorLiveState]:
        with self._lock:
            return list(self._sensors.values())

    def snapshot(self) -> dict:
        """Full state snapshot for WebSocket broadcast."""
        with self._lock:
            return {
                "ts":      int(time.time()),
                "sensors": [s.to_dict() for s in self._sensors.values()],
            }

    # ── Internal ──────────────────────────────────────────────

    def _get_or_create(self, sensor_id: str, name: str = None) -> SensorLiveState:
        if sensor_id not in self._sensors:
            self._sensors[sensor_id] = SensorLiveState(
                sensor_id=sensor_id,
                name=name or sensor_id,
            )
        elif name:
            self._sensors[sensor_id].name = name
        return self._sensors[sensor_id]

    def _notify(self):
        if self._on_change:
            try:
                self._on_change()
            except Exception as e:
                log.warning(f"State change callback error: {e}")


# Module-level singleton
state = DisplayState()
