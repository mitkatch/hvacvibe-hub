"""
engine_store.py — SQLite-backed sensor state store.

Persists:
  - Latest reading per sensor (for power-loss recovery)
  - Per-minute history for daily chart
  - Sync cursor (last minute sent to cloud)

Thread-safe. Uses WAL mode for write performance on Pi SD card.
"""

import logging
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("engine_store")


@dataclass
class SensorRecord:
    sensor_id:  str
    name:       str
    address:    str
    connected:  bool  = False
    vib_rms:    float = 0.0
    vib_peak:   float = 0.0
    dominant_hz: float = 0.0
    alarm:      bool  = False
    warn:       bool  = False
    temp_c:     float = 0.0
    humidity:   float = 0.0
    pressure:   int   = 0
    battery:    int   = 0
    rssi:       int   = -99
    last_seen:  float = 0.0   # unix timestamp


class EngineStore:
    def __init__(self):
        self._db:   sqlite3.Connection | None = None
        self._lock  = threading.RLock()
        # In-memory live state — fast reads for MQTT publisher
        self._live: dict[str, SensorRecord] = {}

    # ── Init ──────────────────────────────────────────────────

    def init(self, db_path: str):
        import os
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._create_tables()
        self._load_live_state()
        log.info(f"Store initialized: {db_path}")

    def _create_tables(self):
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS sensors (
                sensor_id   TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                address     TEXT NOT NULL,
                connected   INTEGER DEFAULT 0,
                vib_rms     REAL    DEFAULT 0,
                vib_peak    REAL    DEFAULT 0,
                dominant_hz REAL    DEFAULT 0,
                alarm       INTEGER DEFAULT 0,
                warn        INTEGER DEFAULT 0,
                temp_c      REAL    DEFAULT 0,
                humidity    REAL    DEFAULT 0,
                pressure    INTEGER DEFAULT 0,
                battery     INTEGER DEFAULT 0,
                rssi        INTEGER DEFAULT -99,
                last_seen   REAL    DEFAULT 0,
                updated_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS history (
                sensor_id   TEXT    NOT NULL,
                minute_of_day INTEGER NOT NULL,
                date        TEXT    NOT NULL,
                vib_rms     REAL,
                temp_c      REAL,
                humidity    REAL,
                synced      INTEGER DEFAULT 0,
                PRIMARY KEY (sensor_id, date, minute_of_day)
            );

            CREATE INDEX IF NOT EXISTS idx_history_sensor_date
                ON history(sensor_id, date);
        """)
        self._db.commit()

    def _load_live_state(self):
        """Restore in-memory state from DB on startup (power recovery)."""
        with self._lock:
            cur = self._db.execute("SELECT * FROM sensors")
            cols = [d[0] for d in cur.description]
            for row in cur.fetchall():
                d = dict(zip(cols, row))
                rec = SensorRecord(
                    sensor_id   = d["sensor_id"],
                    name        = d["name"],
                    address     = d["address"],
                    connected   = False,   # always start disconnected
                    vib_rms     = d["vib_rms"],
                    vib_peak    = d["vib_peak"],
                    dominant_hz = d["dominant_hz"],
                    alarm       = bool(d["alarm"]),
                    warn        = bool(d["warn"]),
                    temp_c      = d["temp_c"],
                    humidity    = d["humidity"],
                    pressure    = d["pressure"],
                    battery     = d["battery"],
                    rssi        = d["rssi"],
                    last_seen   = d["last_seen"],
                )
                self._live[d["sensor_id"]] = rec
                log.info(f"Restored sensor: {rec.name} ({rec.sensor_id})")

    # ── Write ─────────────────────────────────────────────────

    def update_sensor(self, sensor_id: str, name: str, address: str,
                      vib_summary: dict, env: dict):
        """Update live state + persist to SQLite."""
        import datetime

        now = time.time()
        with self._lock:
            rec = self._live.get(sensor_id) or SensorRecord(
                sensor_id=sensor_id, name=name, address=address
            )
            rec.connected   = True
            rec.name        = name
            rec.address     = address
            rec.vib_rms     = vib_summary.get("vib_rms",    rec.vib_rms)
            rec.vib_peak    = vib_summary.get("vib_peak",   rec.vib_peak)
            rec.dominant_hz = vib_summary.get("dominant_hz", rec.dominant_hz)
            rec.alarm       = vib_summary.get("alarm",      rec.alarm)
            rec.warn        = vib_summary.get("warn",       rec.warn)
            rec.temp_c      = env.get("temp_c",   rec.temp_c)
            rec.humidity    = env.get("humidity", rec.humidity)
            rec.pressure    = env.get("pressure", rec.pressure)
            rec.last_seen   = now
            self._live[sensor_id] = rec

        self._persist_sensor(rec)
        self._persist_history(rec, now)

    def set_disconnected(self, sensor_id: str):
        with self._lock:
            if sensor_id in self._live:
                self._live[sensor_id].connected = False
        self._db.execute(
            "UPDATE sensors SET connected=0 WHERE sensor_id=?", (sensor_id,)
        )
        self._db.commit()

    def update_rssi(self, sensor_id: str, rssi: int):
        with self._lock:
            if sensor_id in self._live:
                self._live[sensor_id].rssi = rssi

    def update_battery(self, sensor_id: str, battery: int):
        with self._lock:
            if sensor_id in self._live:
                self._live[sensor_id].battery = battery

    # ── Read ──────────────────────────────────────────────────

    def get_all(self) -> list[SensorRecord]:
        with self._lock:
            return list(self._live.values())

    def get_rssi(self, sensor_id: str) -> int:
        with self._lock:
            return self._live.get(sensor_id, SensorRecord("","","")).rssi

    def get_battery(self, sensor_id: str) -> int:
        with self._lock:
            return self._live.get(sensor_id, SensorRecord("","","")).battery

    def get_history(self, sensor_id: str, date: str) -> list[dict]:
        """Return [{minute, vib_rms, temp_c, humidity}, ...] for chart."""
        cur = self._db.execute(
            """SELECT minute_of_day, vib_rms, temp_c, humidity
               FROM history WHERE sensor_id=? AND date=?
               ORDER BY minute_of_day""",
            (sensor_id, date),
        )
        return [
            {"minute": r[0], "vib_rms": r[1], "temp_c": r[2], "humidity": r[3]}
            for r in cur.fetchall()
        ]

    # ── Internal persistence ──────────────────────────────────

    def _persist_sensor(self, rec: SensorRecord):
        self._db.execute("""
            INSERT INTO sensors
                (sensor_id, name, address, connected, vib_rms, vib_peak,
                 dominant_hz, alarm, warn, temp_c, humidity, pressure,
                 battery, rssi, last_seen, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, datetime('now'))
            ON CONFLICT(sensor_id) DO UPDATE SET
                name=excluded.name, address=excluded.address,
                connected=excluded.connected, vib_rms=excluded.vib_rms,
                vib_peak=excluded.vib_peak, dominant_hz=excluded.dominant_hz,
                alarm=excluded.alarm, warn=excluded.warn,
                temp_c=excluded.temp_c, humidity=excluded.humidity,
                pressure=excluded.pressure, battery=excluded.battery,
                rssi=excluded.rssi, last_seen=excluded.last_seen,
                updated_at=datetime('now')
        """, (
            rec.sensor_id, rec.name, rec.address, int(rec.connected),
            rec.vib_rms, rec.vib_peak, rec.dominant_hz,
            int(rec.alarm), int(rec.warn),
            rec.temp_c, rec.humidity, rec.pressure,
            rec.battery, rec.rssi, rec.last_seen,
        ))
        self._db.commit()

    def _persist_history(self, rec: SensorRecord, ts: float):
        import datetime
        dt     = datetime.datetime.fromtimestamp(ts)
        date   = dt.strftime("%Y-%m-%d")
        minute = dt.hour * 60 + dt.minute

        self._db.execute("""
            INSERT INTO history (sensor_id, minute_of_day, date, vib_rms, temp_c, humidity)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(sensor_id, date, minute_of_day) DO UPDATE SET
                vib_rms=excluded.vib_rms,
                temp_c=excluded.temp_c,
                humidity=excluded.humidity
        """, (rec.sensor_id, minute, date, rec.vib_rms, rec.temp_c, rec.humidity))
        self._db.commit()


# Module-level singleton
store = EngineStore()
