"""
display_history.py — Reads daily history from engine.db for chart rendering.

SQLite WAL mode allows safe concurrent reads while engine writes.
Returns per-minute RMS + env data for the React chart component.
"""

import datetime
import logging
import sqlite3

log = logging.getLogger("display_history")

_db_path: str = ""
_conn:    sqlite3.Connection | None = None


def init(db_path: str):
    global _db_path, _conn
    _db_path = db_path
    try:
        _conn = sqlite3.connect(db_path, check_same_thread=False)
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.row_factory = sqlite3.Row
        log.info(f"History DB opened: {db_path}")
    except Exception as e:
        log.warning(f"Could not open history DB: {e} — charts will be empty")
        _conn = None


def get_daily_history(sensor_id: str, date: str = None) -> list[dict]:
    """
    Return [{minute, vib_rms, temp_c, humidity}, ...] for one sensor + date.
    Date defaults to today. Returns empty list if DB unavailable.
    """
    if _conn is None:
        return []
    if date is None:
        date = datetime.date.today().strftime("%Y-%m-%d")
    try:
        cur = _conn.execute(
            """SELECT minute_of_day, vib_rms, temp_c, humidity
               FROM history
               WHERE sensor_id = ? AND date = ?
               ORDER BY minute_of_day""",
            (sensor_id, date),
        )
        return [
            {
                "minute":   row["minute_of_day"],
                "vib_rms":  row["vib_rms"],
                "temp_c":   row["temp_c"],
                "humidity": row["humidity"],
            }
            for row in cur.fetchall()
        ]
    except Exception as e:
        log.warning(f"History query error: {e}")
        return []


def get_available_dates(sensor_id: str) -> list[str]:
    """Return list of dates that have history for a sensor."""
    if _conn is None:
        return []
    try:
        cur = _conn.execute(
            "SELECT DISTINCT date FROM history WHERE sensor_id=? ORDER BY date DESC",
            (sensor_id,),
        )
        return [row["date"] for row in cur.fetchall()]
    except Exception as e:
        log.warning(f"Dates query error: {e}")
        return []
