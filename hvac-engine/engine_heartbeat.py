"""
engine_heartbeat.py — Publishes gateway/status every 30 seconds.

Payload includes Pi CPU, memory, uptime, sensor count, MQTT status.
Topic: hvac/{gateway_id}/gateway/status
"""

import logging
import threading
import time

log = logging.getLogger("engine_heartbeat")

INTERVAL_SEC = 30


def _get_pi_stats() -> dict:
    """Read Pi system stats. Returns safe defaults if unavailable."""
    stats = {"cpu_pct": 0.0, "mem_pct": 0.0, "uptime_sec": 0, "temp_c": 0.0}
    try:
        import psutil
        stats["cpu_pct"] = round(psutil.cpu_percent(interval=0.5), 1)
        mem = psutil.virtual_memory()
        stats["mem_pct"] = round(mem.percent, 1)
        stats["uptime_sec"] = int(time.time() - psutil.boot_time())
    except ImportError:
        # psutil optional — try /proc directly
        try:
            with open("/proc/uptime") as f:
                stats["uptime_sec"] = int(float(f.read().split()[0]))
        except Exception:
            pass
        try:
            with open("/proc/meminfo") as f:
                lines = dict(
                    line.strip().split(":")
                    for line in f if ":" in line
                )
                total = int(lines["MemTotal"].split()[0])
                avail = int(lines["MemAvailable"].split()[0])
                stats["mem_pct"] = round((1 - avail / total) * 100, 1)
        except Exception:
            pass

    # CPU temperature (Pi-specific)
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            stats["temp_c"] = round(int(f.read().strip()) / 1000.0, 1)
    except Exception:
        pass

    return stats


def _get_ip() -> str:
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "unknown"


class Heartbeat:
    def __init__(self):
        self._thread = None
        self._stop   = threading.Event()

    def start(self, config, mqtt_client):
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop,
            args=(config, mqtt_client),
            name="heartbeat",
            daemon=True,
        )
        self._thread.start()
        log.info("Heartbeat thread started")

    def stop(self):
        self._stop.set()

    def _loop(self, config, mqtt_client):
        from engine_store import store

        # Publish immediately on start, then every INTERVAL_SEC
        while not self._stop.is_set():
            try:
                pi_stats = _get_pi_stats()
                sensors  = store.get_all()
                payload  = {
                    "ts":               int(time.time()),
                    "gateway_id":       config.gateway_id,
                    "gateway_name":     config.gateway_name,
                    "ip":               _get_ip(),
                    "uptime_sec":       pi_stats["uptime_sec"],
                    "cpu_pct":          pi_stats["cpu_pct"],
                    "mem_pct":          pi_stats["mem_pct"],
                    "cpu_temp_c":       pi_stats["temp_c"],
                    "sensors_total":    len(sensors),
                    "sensors_connected": sum(1 for s in sensors if s.connected),
                    "mqtt_connected":   mqtt_client.connected,
                }
                mqtt_client.publish(
                    topic=config.topic("gateway", "status"),
                    payload=payload,
                    qos=0,
                    retain=True,
                )
                log.debug(f"Heartbeat: {len(sensors)} sensors, "
                          f"cpu={pi_stats['cpu_pct']}% "
                          f"mem={pi_stats['mem_pct']}%")
            except Exception as e:
                log.warning(f"Heartbeat error: {e}")

            self._stop.wait(timeout=INTERVAL_SEC)


# Module-level singleton
heartbeat = Heartbeat()
