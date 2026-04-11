"""
setup_db.py — Sensor profile management in engine.db.

Adds sensor_profiles table to the existing engine.db.
Keeps permanent sensor_id as key, human metadata as editable fields.

Relationship:
  sensors table        — live state, written by hvac-engine (don't touch)
  sensor_profiles      — human metadata, written by hvac-setup portal

Join for display:
  SELECT p.display_name, p.asset_type, p.location,
         s.vib_rms, s.kurtosis_x, s.connected, s.last_seen
  FROM sensor_profiles p
  LEFT JOIN sensors s USING (sensor_id)
"""

import logging
import sqlite3
import threading
from datetime import datetime

log = logging.getLogger("setup_db")

DB_PATH = "/home/mitkatch/hvac-engine/engine.db"


class SetupDB:
    def __init__(self, db_path: str = DB_PATH):
        self._db_path = db_path
        self._lock    = threading.RLock()
        self._db      = None

    def init(self):
        self._db = sqlite3.connect(self._db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._create_tables()
        self._sync_from_sensors()
        log.info(f"SetupDB initialized: {self._db_path}")

    def _create_tables(self):
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS sensor_profiles (
                sensor_id    TEXT PRIMARY KEY,
                ble_mac      TEXT NOT NULL,
                display_name TEXT,
                asset_type   TEXT DEFAULT '',
                location     TEXT DEFAULT '',
                added_at     TEXT DEFAULT (datetime('now')),
                updated_at   TEXT DEFAULT (datetime('now')),
                active       INTEGER DEFAULT 1
            );
        """)
        self._db.commit()
        log.info("sensor_profiles table ready")

    def _sync_from_sensors(self):
        """
        Auto-create profiles for any sensors in the sensors table
        that don't have a profile yet.
        """
        with self._lock:
            cur = self._db.execute(
                "SELECT sensor_id, name, address FROM sensors"
            )
            rows = cur.fetchall()
            for row in rows:
                existing = self._db.execute(
                    "SELECT sensor_id FROM sensor_profiles WHERE sensor_id=?",
                    (row["sensor_id"],)
                ).fetchone()
                if not existing:
                    self._db.execute("""
                        INSERT INTO sensor_profiles
                            (sensor_id, ble_mac, display_name)
                        VALUES (?, ?, ?)
                    """, (row["sensor_id"], row["address"], row["name"]))
                    log.info(f"Auto-created profile: {row['sensor_id']}")
            self._db.commit()

    # ── Read ───────────────────────────────────────────────────────────────

    def get_all_sensors(self) -> list[dict]:
        """
        Return all sensor profiles joined with live state from sensors table.
        """
        with self._lock:
            cur = self._db.execute("""
                SELECT
                    p.sensor_id,
                    p.ble_mac,
                    COALESCE(p.display_name, p.sensor_id) AS display_name,
                    p.asset_type,
                    p.location,
                    p.added_at,
                    p.updated_at,
                    p.active,
                    s.connected,
                    s.vib_rms,
                    s.kurtosis_x,
                    s.last_seen,
                    s.rssi,
                    s.battery
                FROM sensor_profiles p
                LEFT JOIN sensors s USING (sensor_id)
                WHERE p.active = 1
                ORDER BY p.display_name
            """)
            return [dict(row) for row in cur.fetchall()]

    def get_sensor(self, sensor_id: str) -> dict | None:
        with self._lock:
            cur = self._db.execute("""
                SELECT p.*, s.connected, s.vib_rms, s.last_seen
                FROM sensor_profiles p
                LEFT JOIN sensors s USING (sensor_id)
                WHERE p.sensor_id = ?
            """, (sensor_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    # ── Write ──────────────────────────────────────────────────────────────

    def update_profile(self, sensor_id: str, display_name: str = None,
                       asset_type: str = None, location: str = None) -> bool:
        """Update human metadata for a sensor profile."""
        with self._lock:
            # Build update dynamically — only set provided fields
            fields = {"updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
            if display_name is not None:
                fields["display_name"] = display_name.strip()
            if asset_type is not None:
                fields["asset_type"] = asset_type.strip()
            if location is not None:
                fields["location"] = location.strip()

            set_clause = ", ".join(f"{k}=?" for k in fields)
            values     = list(fields.values()) + [sensor_id]

            result = self._db.execute(
                f"UPDATE sensor_profiles SET {set_clause} WHERE sensor_id=?",
                values
            )
            self._db.commit()

            if result.rowcount == 0:
                log.warning(f"No profile found for sensor_id={sensor_id}")
                return False

            log.info(f"Updated profile: {sensor_id} → {fields}")
            return True

    def add_sensor(self, sensor_id: str, ble_mac: str,
                   display_name: str = None) -> bool:
        """Add a new sensor profile (called when a new sensor is discovered)."""
        with self._lock:
            try:
                self._db.execute("""
                    INSERT INTO sensor_profiles
                        (sensor_id, ble_mac, display_name)
                    VALUES (?, ?, ?)
                """, (
                    sensor_id,
                    ble_mac,
                    display_name or sensor_id
                ))
                self._db.commit()
                log.info(f"Added sensor profile: {sensor_id}")
                return True
            except sqlite3.IntegrityError:
                log.info(f"Profile already exists: {sensor_id}")
                return False

    def remove_sensor(self, sensor_id: str) -> bool:
        """Soft-delete a sensor profile."""
        with self._lock:
            result = self._db.execute(
                "UPDATE sensor_profiles SET active=0, updated_at=datetime('now') "
                "WHERE sensor_id=?",
                (sensor_id,)
            )
            self._db.commit()
            log.info(f"Removed sensor profile: {sensor_id}")
            return result.rowcount > 0

    def restore_sensor(self, sensor_id: str) -> bool:
        """Restore a soft-deleted sensor profile."""
        with self._lock:
            result = self._db.execute(
                "UPDATE sensor_profiles SET active=1, updated_at=datetime('now') "
                "WHERE sensor_id=?",
                (sensor_id,)
            )
            self._db.commit()
            return result.rowcount > 0


# Module singleton
setup_db = SetupDB()
