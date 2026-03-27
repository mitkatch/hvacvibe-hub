"""
engine_store.py — SQLite-backed sensor state store.

Persists:
  - Latest reading per sensor   (sensors table, for power-loss recovery)
  - Per-minute time-domain data (history_time table, minute granularity)
  - Per-burst FFT/fault data    (history_fft table, unix timestamp granularity)

Two independent write paths — no pairing logic needed:
  update_time_stats() → history_time   (rms, crest, kurtosis per minute)
  update_fft_stats()  → history_fft    (bpfo/bpfi/bsf/ftf per burst)

Join for ML:
  SELECT t.*, f.*
  FROM history_time t
  LEFT JOIN history_fft f
    ON t.sensor_id = f.sensor_id
   AND t.date = f.date
   AND t.minute_of_day = f.minute_of_day

Thread-safe. Uses WAL mode for write performance on Pi SD card.
"""

import logging
import sqlite3
import threading
import time
from dataclasses import dataclass

log = logging.getLogger("engine_store")


@dataclass
class SensorRecord:
    sensor_id:   str
    name:        str
    address:     str
    connected:   bool  = False
    # Time-domain live state
    vib_rms:     float = 0.0
    vib_peak:    float = 0.0
    dominant_hz: float = 0.0
    alarm:       bool  = False
    warn:        bool  = False
    crest_x:     float = 0.0
    crest_y:     float = 0.0
    crest_z:     float = 0.0
    kurtosis_x:  float = 0.0
    kurtosis_y:  float = 0.0
    kurtosis_z:  float = 0.0
    # FFT live state (last burst)
    x_bpfo:      float = 0.0
    x_bpfi:      float = 0.0
    x_bsf:       float = 0.0
    x_ftf:       float = 0.0
    x_snr_bpfo:  float = 0.0
    max_snr_bpfo: float = 0.0
    # Environmental live state
    temp_c:      float = 0.0
    humidity:    float = 0.0
    pressure:    int   = 0
    # Device state
    battery:     int   = 0
    rssi:        int   = -99
    last_seen:   float = 0.0


class EngineStore:
    def __init__(self):
        self._db:  sqlite3.Connection | None = None
        self._lock = threading.RLock()
        # In-memory live state — fast reads for MQTT publisher
        self._live: dict[str, SensorRecord] = {}

    # ── Init ──────────────────────────────────────────────────────────────

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
            -- ── sensors: one row per sensor, live state ──────────────────
            CREATE TABLE IF NOT EXISTS sensors (
                sensor_id    TEXT PRIMARY KEY,
                name         TEXT NOT NULL,
                address      TEXT NOT NULL,
                connected    INTEGER DEFAULT 0,
                vib_rms      REAL    DEFAULT 0,
                vib_peak     REAL    DEFAULT 0,
                dominant_hz  REAL    DEFAULT 0,
                alarm        INTEGER DEFAULT 0,
                warn         INTEGER DEFAULT 0,
                crest_x      REAL    DEFAULT 0,
                crest_y      REAL    DEFAULT 0,
                crest_z      REAL    DEFAULT 0,
                kurtosis_x   REAL    DEFAULT 0,
                kurtosis_y   REAL    DEFAULT 0,
                kurtosis_z   REAL    DEFAULT 0,
                x_bpfo       REAL    DEFAULT 0,
                x_bpfi       REAL    DEFAULT 0,
                x_bsf        REAL    DEFAULT 0,
                x_ftf        REAL    DEFAULT 0,
                x_snr_bpfo   REAL    DEFAULT 0,
                max_snr_bpfo REAL    DEFAULT 0,
                temp_c       REAL    DEFAULT 0,
                humidity     REAL    DEFAULT 0,
                pressure     INTEGER DEFAULT 0,
                battery      INTEGER DEFAULT 0,
                rssi         INTEGER DEFAULT -99,
                last_seen    REAL    DEFAULT 0,
                updated_at   TEXT    DEFAULT (datetime('now'))
            );

            -- ── history_time: per-minute time-domain aggregates ───────────
            CREATE TABLE IF NOT EXISTS history_time (
                sensor_id     TEXT    NOT NULL,
                minute_of_day INTEGER NOT NULL,
                date          TEXT    NOT NULL,
                vib_rms       REAL,
                vib_peak      REAL,
                dominant_hz   REAL,
                crest_x       REAL,
                crest_y       REAL,
                crest_z       REAL,
                kurtosis_x    REAL,
                kurtosis_y    REAL,
                kurtosis_z    REAL,
                temp_c        REAL,
                humidity      REAL,
                alarm         INTEGER DEFAULT 0,
                warn          INTEGER DEFAULT 0,
                synced        INTEGER DEFAULT 0,
                PRIMARY KEY (sensor_id, date, minute_of_day)
            );

            -- ── history_fft: per-burst FFT fault features ─────────────────
            CREATE TABLE IF NOT EXISTS history_fft (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                sensor_id     TEXT    NOT NULL,
                ts            INTEGER NOT NULL,
                date          TEXT    NOT NULL,
                minute_of_day INTEGER NOT NULL,
                seq           INTEGER,
                x_bpfo        REAL,
                x_bpfi        REAL,
                x_bsf         REAL,
                x_ftf         REAL,
                x_snr_bpfo    REAL,
                max_snr_bpfo  REAL,
                synced        INTEGER DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_time_sensor_date
                ON history_time(sensor_id, date);
            CREATE INDEX IF NOT EXISTS idx_time_unsynced
                ON history_time(synced, date);
            CREATE INDEX IF NOT EXISTS idx_fft_sensor_date
                ON history_fft(sensor_id, date);
            CREATE INDEX IF NOT EXISTS idx_fft_ts
                ON history_fft(sensor_id, ts);
            CREATE INDEX IF NOT EXISTS idx_fft_unsynced
                ON history_fft(synced, date);
        """)
        self._db.commit()

    def _load_live_state(self):
        """Restore in-memory state from DB on startup (power-loss recovery)."""
        with self._lock:
            cur = self._db.execute("SELECT * FROM sensors")
            cols = [d[0] for d in cur.description]
            for row in cur.fetchall():
                d = dict(zip(cols, row))
                rec = SensorRecord(
                    sensor_id    = d["sensor_id"],
                    name         = d["name"],
                    address      = d["address"],
                    connected    = False,
                    vib_rms      = d["vib_rms"],
                    vib_peak     = d["vib_peak"],
                    dominant_hz  = d["dominant_hz"],
                    alarm        = bool(d["alarm"]),
                    warn         = bool(d["warn"]),
                    crest_x      = d["crest_x"],
                    crest_y      = d["crest_y"],
                    crest_z      = d["crest_z"],
                    kurtosis_x   = d["kurtosis_x"],
                    kurtosis_y   = d["kurtosis_y"],
                    kurtosis_z   = d["kurtosis_z"],
                    x_bpfo       = d["x_bpfo"],
                    x_bpfi       = d["x_bpfi"],
                    x_bsf        = d["x_bsf"],
                    x_ftf        = d["x_ftf"],
                    x_snr_bpfo   = d["x_snr_bpfo"],
                    max_snr_bpfo = d["max_snr_bpfo"],
                    temp_c       = d["temp_c"],
                    humidity     = d["humidity"],
                    pressure     = d["pressure"],
                    battery      = d["battery"],
                    rssi         = d["rssi"],
                    last_seen    = d["last_seen"],
                )
                self._live[d["sensor_id"]] = rec
                log.info(f"Restored sensor: {rec.name} ({rec.sensor_id})")

    # ── Write: time-domain stats ───────────────────────────────────────────

    def update_time_stats(self, sensor_id: str, name: str, address: str,
                          vib: dict, env: dict):
        """
        Called on every PKT_TYPE_TIME_STATS burst.
        Updates live state + persists to history_time (per-minute).
        """
        now = time.time()
        with self._lock:
            rec = self._live.get(sensor_id) or SensorRecord(
                sensor_id=sensor_id, name=name, address=address
            )
            rec.connected   = True
            rec.name        = name
            rec.address     = address
            rec.last_seen   = now
            rec.vib_rms     = vib.get("vib_rms",     rec.vib_rms)
            rec.vib_peak    = vib.get("vib_peak",    rec.vib_peak)
            rec.dominant_hz = vib.get("dominant_hz", rec.dominant_hz)
            rec.alarm       = vib.get("alarm",       rec.alarm)
            rec.warn        = vib.get("warn",        rec.warn)
            rec.crest_x     = vib.get("crest_x",     rec.crest_x)
            rec.crest_y     = vib.get("crest_y",     rec.crest_y)
            rec.crest_z     = vib.get("crest_z",     rec.crest_z)
            rec.kurtosis_x  = vib.get("kurtosis_x",  rec.kurtosis_x)
            rec.kurtosis_y  = vib.get("kurtosis_y",  rec.kurtosis_y)
            rec.kurtosis_z  = vib.get("kurtosis_z",  rec.kurtosis_z)
            rec.temp_c      = env.get("temp_c",      rec.temp_c)
            rec.humidity    = env.get("humidity",    rec.humidity)
            rec.pressure    = env.get("pressure",    rec.pressure)
            self._live[sensor_id] = rec

        self._persist_sensor(rec)
        self._persist_history_time(rec, now)

    # ── Write: FFT stats ───────────────────────────────────────────────────

    def update_fft_stats(self, sensor_id: str, name: str, address: str,
                         fft: dict, seq: int):
        """
        Called on every PKT_TYPE_FFT_STATS burst.
        Updates live FFT state + appends a row to history_fft.
        Completely independent of update_time_stats — no pairing needed.
        """
        now = time.time()
        with self._lock:
            rec = self._live.get(sensor_id) or SensorRecord(
                sensor_id=sensor_id, name=name, address=address
            )
            rec.x_bpfo       = fft.get("x_bpfo",       rec.x_bpfo)
            rec.x_bpfi       = fft.get("x_bpfi",       rec.x_bpfi)
            rec.x_bsf        = fft.get("x_bsf",        rec.x_bsf)
            rec.x_ftf        = fft.get("x_ftf",        rec.x_ftf)
            rec.x_snr_bpfo   = fft.get("x_snr_bpfo",   rec.x_snr_bpfo)
            rec.max_snr_bpfo = fft.get("max_snr_bpfo", rec.max_snr_bpfo)
            self._live[sensor_id] = rec

        self._persist_history_fft(sensor_id, fft, seq, now)

    # ── Write: sensor device state ─────────────────────────────────────────

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

    # ── Read ───────────────────────────────────────────────────────────────

    def get_all(self) -> list[SensorRecord]:
        with self._lock:
            return list(self._live.values())

    def get_rssi(self, sensor_id: str) -> int:
        with self._lock:
            return self._live.get(sensor_id, SensorRecord("", "", "")).rssi

    def get_battery(self, sensor_id: str) -> int:
        with self._lock:
            return self._live.get(sensor_id, SensorRecord("", "", "")).battery

    def get_history_time(self, sensor_id: str, date: str) -> list[dict]:
        """Return time-domain history for chart display."""
        cur = self._db.execute(
            """SELECT minute_of_day, vib_rms, temp_c, humidity,
                      kurtosis_x, crest_x, alarm, warn
               FROM history_time
               WHERE sensor_id=? AND date=?
               ORDER BY minute_of_day""",
            (sensor_id, date),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def get_history_fft(self, sensor_id: str, date: str) -> list[dict]:
        """Return FFT fault history for a given date."""
        cur = self._db.execute(
            """SELECT ts, minute_of_day, seq,
                      x_bpfo, x_bpfi, x_bsf, x_ftf,
                      x_snr_bpfo, max_snr_bpfo
               FROM history_fft
               WHERE sensor_id=? AND date=?
               ORDER BY ts""",
            (sensor_id, date),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    # ── Internal persistence ───────────────────────────────────────────────

    def _persist_sensor(self, rec: SensorRecord):
        self._db.execute("""
            INSERT INTO sensors
                (sensor_id, name, address, connected,
                 vib_rms, vib_peak, dominant_hz, alarm, warn,
                 crest_x, crest_y, crest_z,
                 kurtosis_x, kurtosis_y, kurtosis_z,
                 x_bpfo, x_bpfi, x_bsf, x_ftf, x_snr_bpfo, max_snr_bpfo,
                 temp_c, humidity, pressure,
                 battery, rssi, last_seen, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
            ON CONFLICT(sensor_id) DO UPDATE SET
                name=excluded.name, address=excluded.address,
                connected=excluded.connected,
                vib_rms=excluded.vib_rms, vib_peak=excluded.vib_peak,
                dominant_hz=excluded.dominant_hz,
                alarm=excluded.alarm, warn=excluded.warn,
                crest_x=excluded.crest_x, crest_y=excluded.crest_y,
                crest_z=excluded.crest_z,
                kurtosis_x=excluded.kurtosis_x, kurtosis_y=excluded.kurtosis_y,
                kurtosis_z=excluded.kurtosis_z,
                x_bpfo=excluded.x_bpfo, x_bpfi=excluded.x_bpfi,
                x_bsf=excluded.x_bsf, x_ftf=excluded.x_ftf,
                x_snr_bpfo=excluded.x_snr_bpfo, max_snr_bpfo=excluded.max_snr_bpfo,
                temp_c=excluded.temp_c, humidity=excluded.humidity,
                pressure=excluded.pressure,
                battery=excluded.battery, rssi=excluded.rssi,
                last_seen=excluded.last_seen, updated_at=datetime('now')
        """, (
            rec.sensor_id, rec.name, rec.address, int(rec.connected),
            rec.vib_rms, rec.vib_peak, rec.dominant_hz,
            int(rec.alarm), int(rec.warn),
            rec.crest_x, rec.crest_y, rec.crest_z,
            rec.kurtosis_x, rec.kurtosis_y, rec.kurtosis_z,
            rec.x_bpfo, rec.x_bpfi, rec.x_bsf, rec.x_ftf,
            rec.x_snr_bpfo, rec.max_snr_bpfo,
            rec.temp_c, rec.humidity, rec.pressure,
            rec.battery, rec.rssi, rec.last_seen,
        ))
        self._db.commit()

    def _persist_history_time(self, rec: SensorRecord, ts: float):
        import datetime
        dt     = datetime.datetime.fromtimestamp(ts)
        date   = dt.strftime("%Y-%m-%d")
        minute = dt.hour * 60 + dt.minute

        self._db.execute("""
            INSERT INTO history_time (
                sensor_id, minute_of_day, date,
                vib_rms, vib_peak, dominant_hz,
                crest_x, crest_y, crest_z,
                kurtosis_x, kurtosis_y, kurtosis_z,
                temp_c, humidity, alarm, warn
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(sensor_id, date, minute_of_day) DO UPDATE SET
                vib_rms=excluded.vib_rms,
                vib_peak=excluded.vib_peak,
                dominant_hz=excluded.dominant_hz,
                crest_x=excluded.crest_x, crest_y=excluded.crest_y,
                crest_z=excluded.crest_z,
                kurtosis_x=excluded.kurtosis_x, kurtosis_y=excluded.kurtosis_y,
                kurtosis_z=excluded.kurtosis_z,
                temp_c=excluded.temp_c, humidity=excluded.humidity,
                alarm=excluded.alarm, warn=excluded.warn
        """, (
            rec.sensor_id, minute, date,
            rec.vib_rms, rec.vib_peak, rec.dominant_hz,
            rec.crest_x, rec.crest_y, rec.crest_z,
            rec.kurtosis_x, rec.kurtosis_y, rec.kurtosis_z,
            rec.temp_c, rec.humidity,
            int(rec.alarm), int(rec.warn),
        ))
        self._db.commit()

    def _persist_history_fft(self, sensor_id: str, fft: dict,
                              seq: int, ts: float):
        import datetime
        dt     = datetime.datetime.fromtimestamp(ts)
        date   = dt.strftime("%Y-%m-%d")
        minute = dt.hour * 60 + dt.minute

        self._db.execute("""
            INSERT INTO history_fft (
                sensor_id, ts, date, minute_of_day, seq,
                x_bpfo, x_bpfi, x_bsf, x_ftf,
                x_snr_bpfo, max_snr_bpfo
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (
            sensor_id, int(ts), date, minute, seq,
            fft.get("x_bpfo"),
            fft.get("x_bpfi"),
            fft.get("x_bsf"),
            fft.get("x_ftf"),
            fft.get("x_snr_bpfo"),
            fft.get("max_snr_bpfo"),
        ))
        self._db.commit()


# Module-level singleton
store = EngineStore()
