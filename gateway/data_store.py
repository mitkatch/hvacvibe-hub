"""
Data Store — thread-safe shared state for N sensors.

All modules read/write through this store.
No direct coupling between ble_scanner, display, and cloud_sync.

History: one float per minute-of-day (0-1439), resets at midnight.
"""
import threading
import datetime
from dataclasses import dataclass, field
from typing import Optional
from config import ALARMS, STORE


@dataclass
class SensorReading:
    """One timestamped reading from a sensor."""
    ts:        datetime.datetime
    vib_rms:   float
    vib_peak:  float
    temp:      float
    humidity:  float
    pressure:  float
    battery:   int
    rssi:      int

    def to_dict(self) -> dict:
        return {
            "ts":        self.ts.isoformat(),
            "vib_rms":   round(self.vib_rms,  4),
            "vib_peak":  round(self.vib_peak, 4),
            "temp":      round(self.temp,      2),
            "humidity":  round(self.humidity,  2),
            "battery":   self.battery,
            "rssi":      self.rssi,
        }


@dataclass
class SensorState:
    """Full state for one sensor."""
    address:   str
    name:      str

    # Live values (updated every BLE poll)
    connected:    bool                    = False
    last_seen:    Optional[datetime.datetime] = None
    vib_rms:      float                   = 0.0
    vib_peak:     float                   = 0.0
    temp:         float                   = 0.0
    humidity:     float                   = 0.0
    pressure:     float                   = 0.0
    battery:      int                     = 0
    rssi:         int                     = -99
    alarm:        bool                    = False
    warn:         bool                    = False

    # Daily history: minute_of_day -> SensorReading
    history:      dict = field(default_factory=dict)

    # Cloud sync cursor: last minute successfully sent
    synced_up_to: int  = -1

    # Internal: last minute we logged to history
    _last_history_min: int = field(default=-1, repr=False)

    def update(self, reading: SensorReading):
        """Apply a new live reading, update history if interval elapsed."""
        self.connected = True
        self.last_seen = reading.ts
        self.vib_rms   = reading.vib_rms
        self.vib_peak  = reading.vib_peak
        self.temp      = reading.temp
        self.humidity  = reading.humidity
        self.pressure  = reading.pressure
        self.battery   = reading.battery
        self.rssi      = reading.rssi
        self.alarm     = reading.vib_rms >= ALARMS["vib_rms_alarm"]
        self.warn      = reading.vib_rms >= ALARMS["vib_rms_warn"]

        # Log one sample per minute to history
        cur_min = reading.ts.hour * 60 + reading.ts.minute
        if cur_min != self._last_history_min:
            self.history[cur_min]   = reading
            self._last_history_min  = cur_min

    def reset_day(self):
        """Called at midnight — clear history and sync cursor."""
        self.history       = {}
        self.synced_up_to  = -1
        self._last_history_min = -1

    def get_unsynced(self) -> list[tuple[int, SensorReading]]:
        """Return list of (minute, reading) not yet sent to cloud."""
        return sorted(
            [(m, r) for m, r in self.history.items() if m > self.synced_up_to],
            key=lambda x: x[0]
        )

    def mark_synced(self, up_to_minute: int):
        self.synced_up_to = up_to_minute

    def history_list(self) -> list[list]:
        """Return [[minute, rms], ...] sorted for chart rendering."""
        return [[m, r.vib_rms] for m, r in sorted(self.history.items())]

    def live_dict(self) -> dict:
        return {
            "name":      self.name,
            "address":   self.address,
            "connected": self.connected,
            "vib_rms":   self.vib_rms,
            "vib_peak":  self.vib_peak,
            "temp":      self.temp,
            "humidity":  self.humidity,
            "pressure":  self.pressure,
            "battery":   self.battery,
            "rssi":      self.rssi,
            "alarm":     self.alarm,
            "warn":      self.warn,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
        }


class DataStore:
    """
    Thread-safe store for all sensor states.
    Single instance shared across all modules via module-level STORE.
    """

    def __init__(self):
        self._lock   = threading.RLock()
        self._sensors: dict[str, SensorState] = {}

    # ── Write (called by ble_scanner) ─────────────────────────

    def update(self, address: str, name: str, reading: SensorReading):
        """Upsert sensor state keyed by NAME — address may change (BLE randomisation)."""
        with self._lock:
            if name not in self._sensors:
                self._sensors[name] = SensorState(address=address, name=name)
            else:
                # Update address in case it changed
                self._sensors[name].address = address
            self._sensors[name].update(reading)

    def set_disconnected(self, address: str):
        """Mark sensor disconnected — find by address since name may not be known."""
        with self._lock:
            for s in self._sensors.values():
                if s.address == address:
                    s.connected = False
                    break

    # ── Read (called by display + cloud_sync) ─────────────────

    def get_all(self) -> list[SensorState]:
        """Return all sensors — already unique by name (name is the key)."""
        with self._lock:
            return list(self._sensors.values())

    def get_by_address(self, address: str) -> Optional[SensorState]:
        with self._lock:
            for s in self._sensors.values():
                if s.address == address:
                    return s
            return None

    def get_by_name(self, name: str) -> Optional[SensorState]:
        with self._lock:
            return self._sensors.get(name)

    def sensor_count(self) -> int:
        with self._lock:
            return len(self._sensors)

    def get_unsynced_all(self) -> dict[str, list[tuple[int, SensorReading]]]:
        """Return {name: [(minute, reading), ...]} for cloud sync."""
        with self._lock:
            return {
                name: s.get_unsynced()
                for name, s in self._sensors.items()
                if s.get_unsynced()
            }

    def mark_synced(self, name: str, up_to_minute: int):
        with self._lock:
            if name in self._sensors:
                self._sensors[name].mark_synced(up_to_minute)

    # ── Midnight reset ────────────────────────────────────────

    def reset_all_days(self):
        with self._lock:
            for s in self._sensors.values():
                s.reset_day()

    def sensor_names(self) -> list[str]:
        with self._lock:
            return list(self._sensors.keys())


# Module-level singleton — import this everywhere
store = DataStore()
