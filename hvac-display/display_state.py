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
class FFTAxisStats:
    dominant_hz:  float = 0.0
    dominant_mag: float = 0.0
    total_power:  float = 0.0
    bpfo_energy:  float = 0.0
    bpfi_energy:  float = 0.0
    bsf_energy:   float = 0.0
    ftf_energy:   float = 0.0
    noise_floor:  float = 0.0
    snr_bpfo:     float = 0.0

    def to_dict(self) -> dict:
        return {
            "dominant_hz":  self.dominant_hz,
            "dominant_mag": self.dominant_mag,
            "total_power":  self.total_power,
            "bpfo_energy":  self.bpfo_energy,
            "bpfi_energy":  self.bpfi_energy,
            "bsf_energy":   self.bsf_energy,
            "ftf_energy":   self.ftf_energy,
            "noise_floor":  self.noise_floor,
            "snr_bpfo":     self.snr_bpfo,
        }


@dataclass
class SensorLiveState:
    sensor_id:    str
    name:         str   = "Unknown"
    connected:    bool  = False
    vib_rms:      float = 0.0
    vib_peak:     float = 0.0
    dominant_hz:  float = 0.0
    alarm:        bool  = False
    warn:         bool  = False
    temp_c:       float = 0.0
    humidity:     float = 0.0
    pressure:     int   = 0
    battery:      int   = 0
    rssi:         int   = -99
    last_seen:    float = 0.0
    alert_level:  str   = "ok"   # "ok" | "warn" | "alarm"
    max_snr_bpfo:  float = 0.0

    # FFT fault stats per axis — updated on each vibration/fft_stats message
    fft_x: FFTAxisStats = field(default_factory=FFTAxisStats)
    fft_y: FFTAxisStats = field(default_factory=FFTAxisStats)
    fft_z: FFTAxisStats = field(default_factory=FFTAxisStats)

    # X-axis frequency spectrum — updated on each vibration/spectrum message
    spectrum_freq: list = field(default_factory=list)
    spectrum_amp:  list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "sensor_id":    self.sensor_id,
            "name":         self.name,
            "connected":    self.connected,
            "vib_rms":      self.vib_rms,
            "vib_peak":     self.vib_peak,
            "dominant_hz":  self.dominant_hz,
            "alarm":        self.alarm,
            "warn":         self.warn,
            "temp_c":       self.temp_c,
            "humidity":     self.humidity,
            "pressure":     self.pressure,
            "battery":      self.battery,
            "rssi":         self.rssi,
            "last_seen":    self.last_seen,
            "alert_level":  self.alert_level,
            "max_snr_bpfo": self.max_snr_bpfo,
            "fft": {
                "x": self.fft_x.to_dict(),
                "y": self.fft_y.to_dict(),
                "z": self.fft_z.to_dict(),
            },
            "spectrum": {
                "freq_hz":   self.spectrum_freq,
                "amplitude": self.spectrum_amp,
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
            # MQTT publishes "vector_rms_g" and "vib_peak_g" — map correctly
            s.vib_rms     = payload.get("vector_rms_g", payload.get("vib_rms",  s.vib_rms))
            s.vib_peak    = payload.get("vib_peak_g",   payload.get("vib_peak", s.vib_peak))
            s.dominant_hz = payload.get("dominant_hz",  s.dominant_hz)
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
            s.temp_c   = payload.get("temp_c",    s.temp_c)
            s.humidity = payload.get("humidity",  s.humidity)
            if "pressure_pa" in payload:
                s.pressure = round(payload["pressure_pa"])
            elif "pressure_hpa" in payload:
                s.pressure = round(payload["pressure_hpa"])
        self._notify()

    def handle_fft_stats(self, sensor_id: str, payload: dict):
        with self._lock:
            s = self._get_or_create(sensor_id)
            s.fft_x = FFTAxisStats(
                dominant_hz  = payload.get("x_dominant_hz",  0.0),
                dominant_mag = payload.get("x_dominant_mag", 0.0),
                total_power  = payload.get("x_total_power",  0.0),
                bpfo_energy  = payload.get("x_bpfo_energy",  0.0),
                bpfi_energy  = payload.get("x_bpfi_energy",  0.0),
                bsf_energy   = payload.get("x_bsf_energy",   0.0),
                ftf_energy   = payload.get("x_ftf_energy",   0.0),
                noise_floor  = payload.get("x_noise_floor",  0.0),
                snr_bpfo     = payload.get("x_snr_bpfo",     0.0),
            )
            s.fft_y = FFTAxisStats(
                dominant_hz = payload.get("y_dominant_hz",  0.0),
                bpfo_energy = payload.get("y_bpfo_energy",  0.0),
                snr_bpfo    = payload.get("y_snr_bpfo",     0.0),
            )
            s.fft_z = FFTAxisStats(
                dominant_hz = payload.get("z_dominant_hz",  0.0),
                bpfo_energy = payload.get("z_bpfo_energy",  0.0),
                snr_bpfo    = payload.get("z_snr_bpfo",     0.0),
            )
            s.max_snr_bpfo = payload.get("max_snr_bpfo", s.max_snr_bpfo)
        self._notify()

    def handle_features(self, sensor_id: str, payload: dict):
        with self._lock:
            s = self._get_or_create(sensor_id)
            # MQTT sends dominant_hz as flat field, not nested under axis
            s.vib_rms     = payload.get("vector_rms_g", s.vib_rms)
            s.dominant_hz = payload.get("dominant_hz",  s.dominant_hz)
            s.alarm       = payload.get("alarm", s.alarm)
            s.warn        = payload.get("warn",  s.warn)
        self._notify()  # features DO drive UI — notify on update

    def handle_spectrum(self, sensor_id: str, payload: dict):
        with self._lock:
            s = self._get_or_create(sensor_id)
            s.spectrum_freq = payload.get("freq_hz",   [])
            s.spectrum_amp  = payload.get("amplitude", [])
        self._notify()

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
