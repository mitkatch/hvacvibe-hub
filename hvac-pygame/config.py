"""
config.py — HVAC-Vibe pygame display config.
Minimal — no BLE, no cloud sync needed here.
"""
import platform

ON_PI = platform.system() not in ('Windows', 'Darwin')

DISPLAY = {
    "width":     480,
    "height":    320,
    "fps":       5,
    "fb_device": "/dev/waveshare",
    "rotate":    0,
    "font_mono": "Courier New" if not ON_PI else "monospace",
}

ALARMS = {
    "vib_rms_warn":  0.50,
    "vib_rms_alarm": 0.60,
    "temp_max":      60.0,
    "battery_low":   20,
}

MQTT = {
    "broker": "localhost",
    "port":   1883,
}
STORE = {
    "history_interval_sec": 60,
}
