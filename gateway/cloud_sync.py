"""
Cloud Sync — periodically publishes unsynced sensor history to the cloud.

Runs in its own thread. Only attempts sync when WiFi is available.
If WiFi is down, skips silently — data stays in memory until next cycle.
Yesterday's data is lost on midnight reset if not synced.
"""
import logging
import threading
import time
import datetime
import socket

from data_store import store, SensorReading
from publisher.base import PublishRecord
from publisher import get_publisher
from config import CLOUD

log = logging.getLogger("cloud_sync")


def _wifi_available() -> bool:
    """Quick check: can we reach the internet?"""
    try:
        socket.setdefaulttimeout(3)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(
            ("8.8.8.8", 53))
        return True
    except Exception:
        return False


def _reading_to_record(address: str, name: str,
                       minute: int, reading: SensorReading,
                       date: datetime.date) -> PublishRecord:
    """Convert a store reading to a publish record."""
    ts = datetime.datetime(
        year   = date.year,
        month  = date.month,
        day    = date.day,
        hour   = minute // 60,
        minute = minute % 60,
        second = 0,
    )
    return PublishRecord(
        sensor_id   = address,
        sensor_name = name,
        ts          = ts,
        vib_rms     = reading.vib_rms,
        vib_peak    = reading.vib_peak,
        temp        = reading.temp,
        humidity    = reading.humidity,
        battery     = reading.battery,
        rssi        = reading.rssi,
    )


# Module-level publisher status (read by display)
_status = {
    "enabled":    CLOUD["enabled"],
    "wifi":       False,
    "last_sync":  None,
    "last_error": None,
    "records_sent_today": 0,
}


def get_status() -> dict:
    return dict(_status)


def _sync_loop(publisher):
    interval = CLOUD["check_interval"]
    today    = datetime.date.today()

    while True:
        time.sleep(interval)

        # Midnight reset
        now = datetime.date.today()
        if now != today:
            log.info("Midnight — resetting daily history")
            store.reset_all_days()
            _status["records_sent_today"] = 0
            today = now

        if not CLOUD["enabled"]:
            continue

        # Check connectivity
        wifi = _wifi_available()
        _status["wifi"] = wifi
        if not wifi:
            log.debug("No WiFi — skipping sync")
            continue

        # Get unsynced records from all sensors
        unsynced = store.get_unsynced_all()
        if not unsynced:
            log.debug("Nothing to sync")
            continue

        date = datetime.date.today()
        all_records = []
        record_map  = {}   # track which records belong to which sensor

        for name, minute_readings in unsynced.items():
            sensor = store.get_by_name(name)
            if not sensor:
                continue
            records = [
                _reading_to_record(sensor.address, name, m, r, date)
                for m, r in minute_readings
            ]
            all_records.extend(records)
            record_map[name] = minute_readings

        if not all_records:
            continue

        log.info(f"Syncing {len(all_records)} records from "
                 f"{len(record_map)} sensor(s)")

        result = publisher.publish_batch(all_records)

        if result.success:
            # Mark each sensor's records as synced
            for address, minute_readings in record_map.items():
                if minute_readings:
                    last_minute = minute_readings[-1][0]
                    store.mark_synced(address, last_minute)
            _status["last_sync"]          = datetime.datetime.now().isoformat()
            _status["last_error"]         = None
            _status["records_sent_today"] += result.records_sent
            log.info(f"Sync OK — {result.records_sent} records sent")
        else:
            _status["last_error"] = result.error
            log.warning(f"Sync failed: {result.error}")


def start() -> threading.Thread:
    """Initialize publisher and start sync thread."""
    if not CLOUD["enabled"]:
        log.info("Cloud sync disabled in config")
        return None

    publisher = get_publisher(CLOUD)
    ok = publisher.init()
    if not ok:
        log.warning(f"Publisher init failed: {publisher.status()}")

    t = threading.Thread(
        target  = _sync_loop,
        args    = (publisher,),
        name    = "cloud-sync",
        daemon  = True,
    )
    t.start()
    log.info("Cloud sync thread started")
    return t
