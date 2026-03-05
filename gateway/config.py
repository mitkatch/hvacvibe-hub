"""
HVAC-Vibe Gateway Configuration
All tuneable settings in one place.
"""
import os
import platform

# ── Platform ──────────────────────────────────────────────────
ON_PI = platform.system() not in ('Windows', 'Darwin')

# Force simulation mode (no real BLE hardware needed)
# Set False when nRF52840 firmware is ready and advertising HVACVIBE-*
SIM_MODE = False

# ── Display ───────────────────────────────────────────────────
DISPLAY = {
    "width":       480,
    "height":      320,
    "fps":         5,    # 5fps plenty for sensor dashboard, saves CPU
    "fb_device":   "/dev/fb1",       # framebuffer on Pi
    "rotate":      90,               # degrees to rotate before writing to fb
    "font_mono":   "Courier New" if not ON_PI else "monospace",
}

# ── BLE Scanner ───────────────────────────────────────────────
BLE = {
    "scan_interval":   2.0,          # seconds between scans
    "device_prefix":   "HVAC-Vibe",   # name prefix filter
    "timeout_seconds": 15,           # mark disconnected after this
}

# ── Data Store ────────────────────────────────────────────────
STORE = {
    "history_interval_sec": 60,      # how often to log a history sample
}

# ── Cloud Sync ────────────────────────────────────────────────
CLOUD = {
    "enabled":        True,
    "check_interval": 60,            # seconds between sync attempts
    "publisher":      "http",        # "http" | "mqtt"
    "http": {
        "endpoint":  os.getenv("HVACVIBE_HTTP_URL",
                               "http://localhost:9000/api/readings"),
        "timeout":   10,
        "headers":   {"Content-Type": "application/json",
                      "X-Api-Key":    os.getenv("HVACVIBE_API_KEY", "")},
    },
    "mqtt": {
        "broker":    os.getenv("HVACVIBE_MQTT_HOST", "localhost"),
        "port":      int(os.getenv("HVACVIBE_MQTT_PORT", "1883")),
        "username":  os.getenv("HVACVIBE_MQTT_USER", ""),
        "password":  os.getenv("HVACVIBE_MQTT_PASS", ""),
        "topic_fmt": "hvacvibe/{sensor_id}/data",
        "qos":       1,
    },
}

# ── Alarm Thresholds ──────────────────────────────────────────
ALARMS = {
    "vib_rms_warn":  0.50,
    "vib_rms_alarm": 0.60,
    "temp_max":      60.0,
    "battery_low":   20,
}

# ── Sensor Registry ───────────────────────────────────────────
# Pre-configured sensors — scanner will also discover unnamed ones
SENSORS = [
    {"address": "AA:BB:CC:DD:EE:01", "name": "UNIT-01"},
    # {"address": "AA:BB:CC:DD:EE:02", "name": "UNIT-02"},
]
