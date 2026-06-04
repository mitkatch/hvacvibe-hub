"""
engine_config.py — Engine configuration.

Reads /etc/hvac-vibe/config.json (or ./config.json for dev).
Derives gateway_id = "{gateway_name}-{mac_suffix}".
Falls back to safe defaults if file is missing (first boot).
"""

import json
import logging
import os
import re
import uuid

log = logging.getLogger("engine_config")

# Config file locations — tries in order
_CONFIG_PATHS = [
    "/etc/hvac-vibe/config.json",
    os.path.join(os.path.dirname(__file__), "config.json"),
]

_DEFAULTS = {
    "gateway_name":    "hvac-gw",
    "wifi_ssid":       "",
    "wifi_password":   "",
    "mqtt_broker":     "localhost",
    "mqtt_port":       1883,
    "db_path":         "/home/mitkatch/hvac-engine/engine.db",
    "sensors":         {},
    "sim_mode":        False,
}

# Alarm thresholds
ALARMS = {
    "vib_rms_warn":  0.50,
    "vib_rms_alarm": 0.60,
    "temp_max":      60.0,
    "battery_low":   20,
}

# BLE settings
BLE = {
    "device_prefix":   "HVAC-Vibe",
    "scan_interval":   5.0,
    "connect_timeout": 20.0,
    "retry_delay":     5.0,
}

# FFT settings — must match firmware
SAMPLES_PER_BURST = 512
SAMPLE_RATE_HZ    = 1600       # firmware FIFO rate
NYQUIST_HZ        = SAMPLE_RATE_HZ // 2   # 800 Hz
MG_PER_LSB        = 4
G_PER_MG          = 0.001

# BLE UUIDs — must match nRF52840 firmware
SERVICE_UUID    = "12345678-1234-5678-1234-56789abcdef0"
BURST_DATA_UUID = "12345678-1234-5678-1234-56789abcdef1"
ENV_DATA_UUID   = "12345678-1234-5678-1234-56789abcdef2"


def _get_mac_suffix() -> str:
    """Return last 3 bytes of wlan0 MAC as 6 hex chars, e.g. 'a4b2c3'."""
    try:
        # Try wlan0 first, fall back to any interface
        for iface in ("wlan0", "eth0", "wlan1"):
            path = f"/sys/class/net/{iface}/address"
            if os.path.exists(path):
                with open(path) as f:
                    mac = f.read().strip().replace(":", "")
                    if len(mac) == 12:
                        return mac[6:]   # last 3 bytes
    except Exception:
        pass
    # Fallback: use UUID node (MAC-derived on most systems)
    node = uuid.getnode()
    return f"{node & 0xFFFFFF:06x}"


def _load_raw() -> dict:
    """Load config.json, return raw dict."""
    for path in _CONFIG_PATHS:
        if os.path.exists(path):
            try:
                with open(path) as f:
                    data = json.load(f)
                log.info(f"Config loaded from {path}")
                return data
            except Exception as e:
                log.warning(f"Failed to read {path}: {e}")
    log.warning("No config.json found — using defaults (first boot?)")
    return {}


def _sanitize_name(name: str) -> str:
    """Strip characters unsafe for MQTT topics."""
    return re.sub(r"[^a-zA-Z0-9_\-]", "", name).lower()[:32] or "gw"


class EngineConfig:
    def __init__(self):
        raw = _load_raw()
        merged = {**_DEFAULTS, **raw}

        self.gateway_name: str  = _sanitize_name(merged["gateway_name"])
        self.mac_suffix:   str  = _get_mac_suffix()
        self.gateway_id:   str  = merged.get("gateway_id") or \
                                   f"{self.gateway_name}-{self.mac_suffix}"

        self.wifi_ssid:     str  = merged["wifi_ssid"]
        self.wifi_password: str  = merged["wifi_password"]
        self.mqtt_broker:   str  = merged["mqtt_broker"]
        self.mqtt_port:     int  = int(merged["mqtt_port"])
        self.db_path:       str  = merged["db_path"]
        self.sim_mode:      bool = bool(merged["sim_mode"])

        # sensors: { "sensor_id": { "name": "...", "mac": "..." } }
        self.sensors: dict = merged.get("sensors", {})

        log.info(f"gateway_id={self.gateway_id}  sim={self.sim_mode}")
        # BLE settings — attach to instance for easy access
        self.BLE = BLE

    def topic(self, sensor_id: str, *parts: str) -> str:
        """Build a fully-qualified MQTT topic.

        Examples:
          config.topic("sensor-01", "status")
            → "hvac/roof-unit-a4b2c3/sensor-01/status"
          config.topic("sensor-01", "vibration", "fft")
            → "hvac/roof-unit-a4b2c3/sensor-01/vibration/fft"
          config.topic("gateway", "status")
            → "hvac/roof-unit-a4b2c3/gateway/status"
        """
        return "/".join(["hvac", self.gateway_id, sensor_id] + list(parts))

    def save(self, updates: dict):
        """Persist config updates to the first writable config path."""
        raw = _load_raw()
        raw.update(updates)
        # Recalculate gateway_id if name changed
        if "gateway_name" in updates:
            name = _sanitize_name(updates["gateway_name"])
            raw["gateway_id"] = f"{name}-{self.mac_suffix}"

        for path in _CONFIG_PATHS:
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w") as f:
                    json.dump(raw, f, indent=2)
                log.info(f"Config saved to {path}")
                return
            except PermissionError:
                continue
        log.error("Could not save config — no writable path found")


# Module-level singleton
config = EngineConfig()
